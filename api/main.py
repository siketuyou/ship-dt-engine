# api/main.py
from __future__ import annotations

import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from orchestrator.orchestrator import Orchestrator
from storage.db_manager import DatabaseManager
from storage.csv_importer import CsvImporter
from utils.logger import get_logger

logger = get_logger("SpiderAPI")

app = FastAPI(title="Spider Service")

DB_URL     = "mysql+pymysql://root:Yxy201062@localhost:3306/ship_digital_db"
OUTPUT_DIR = "data/output"
UPLOAD_DIR = Path("data/upload")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ── 全局调度器 ───────────────────────────────────────────
_scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
_scheduler.start()

# ── 运行锁 ───────────────────────────────────────────────
_running_locks: dict[int, bool] = {}
_lock = threading.Lock()


# ================================================================
# Schema
# ================================================================

class RunRequest(BaseModel):
    model_id: int
    sample_limit: Optional[int] = None

class ScheduleRequest(BaseModel):
    model_id: int
    cron_hour: str = "2"
    cron_minute: str = "0"


# ================================================================
# 工具函数
# ================================================================

def _get_conn():
    """每次请求获取一个新的原生连接"""
    return DatabaseManager(DB_URL).get_raw_conn()


def _update_state(db: DatabaseManager, model_id: int, state: str):
    try:
        conn = db.get_raw_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE m_reptile_model SET m_reptile_model_state=%s "
            "WHERE m_reptile_model_id=%s",
            (state, model_id),
        )
        conn.commit()
        cursor.close()
        logger.info(f"model_id={model_id} 状态 → {state}")
    except Exception as e:
        logger.error(f"状态更新失败：{e}")


# ================================================================
# 爬虫触发
# ================================================================

@app.post("/spider/run")
def trigger_spider(req: RunRequest):
    """手动触发爬虫，后台异步执行"""
    with _lock:
        if _running_locks.get(req.model_id):
            raise HTTPException(
                status_code=409,
                detail=f"model_id={req.model_id} 正在运行中"
            )
        _running_locks[req.model_id] = True

    thread = threading.Thread(
        target=_run_pipeline,
        args=(req.model_id, req.sample_limit),
        daemon=True,
    )
    thread.start()
    return {"success": True, "message": f"model_id={req.model_id} 已触发"}


def _run_pipeline(model_id: int, sample_limit: Optional[int]):
    db = DatabaseManager(DB_URL)
    try:
        _update_state(db, model_id, "运行中")
        ok = Orchestrator(
            db_url=DB_URL,
            model_id=model_id,
            sample_limit=sample_limit,
            output_dir=OUTPUT_DIR,
        ).run()
        _update_state(db, model_id, "已完成" if ok else "异常")
    except Exception as e:
        logger.error(f"model_id={model_id} 流水线异常：{e}", exc_info=True)
        _update_state(db, model_id, "异常")
    finally:
        with _lock:
            _running_locks[model_id] = False


# ================================================================
# 爬虫状态查询
# ================================================================

@app.get("/spider/status")
def get_all_status():
    """查询所有爬虫模型状态"""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT m_reptile_model_id, m_reptile_model_name, "
        "m_reptile_model_state, m_reptile_model_web "
        "FROM m_reptile_model WHERE deleted=0"
    )
    rows = cursor.fetchall()
    cursor.close()
    return [
        {
            "model_id":   r[0],
            "name":       r[1],
            "state":      r[2],
            "target_url": r[3],
            "is_running": _running_locks.get(r[0], False),
        }
        for r in rows
    ]


@app.get("/spider/status/{model_id}")
def get_status(model_id: int):
    """查询单个爬虫模型状态"""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT m_reptile_model_id, m_reptile_model_name, "
        "m_reptile_model_state, m_reptile_model_web "
        "FROM m_reptile_model WHERE m_reptile_model_id=%s AND deleted=0",
        (model_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    if not row:
        raise HTTPException(status_code=404, detail="模型不存在")
    return {
        "model_id":   row[0],
        "name":       row[1],
        "state":      row[2],
        "target_url": row[3],
        "is_running": _running_locks.get(model_id, False),
    }


# ================================================================
# CSV 导入
# ================================================================

@app.post("/spider/import")
async def import_csv(
    file: UploadFile = File(...),
    model_log_id: int = Form(...),
    user_id: int = Form(0),
):
    """
    上传 CSV 文件并导入 device 表，写入 csv_enter_logs。
    支持多次导入，每次产生独立日志记录。
    """
    # 保存上传文件（文件名加时间戳防止覆盖）
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{ts}_{file.filename}"
    save_path = UPLOAD_DIR / safe_name

    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    logger.info(f"CSV 上传成功：{save_path}")

    # 执行导入
    conn = _get_conn()
    try:
        result = CsvImporter(conn).run(
            csv_path=save_path,
            model_log_id=model_log_id,
            user_id=user_id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"CSV 导入异常：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导入失败：{e}")

    return result


@app.get("/spider/import/logs/{model_log_id}")
def get_import_logs(model_log_id: int, limit: int = 20):
    """
    查询导入日志，按时间降序返回。
    支持管理员多次导入后查看历史记录。
    """
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT csv_enter_logs_id, csv_enter_number, csv_enter_success_number,
               csv_enter_logs_time, csv_enter_logs, csv_enter_user_id
        FROM csv_enter_logs
        WHERE model_log_id=%s AND deleted=0
        ORDER BY csv_enter_logs_time DESC
        LIMIT %s
        """,
        (model_log_id, limit),
    )
    rows = cursor.fetchall()
    cursor.close()
    return [
        {
            "log_id":    r[0],
            "total":     r[1],
            "success":   r[2],
            "time":      str(r[3]),
            "detail":    r[4],
            "user_id":   r[5],
        }
        for r in rows
    ]


# ================================================================
# 定时器管理
# ================================================================

@app.post("/scheduler/add")
def add_schedule(req: ScheduleRequest):
    """添加或更新定时任务"""
    job_id = f"model_{req.model_id}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)

    _scheduler.add_job(
        func=_run_pipeline,
        trigger=CronTrigger(hour=req.cron_hour, minute=req.cron_minute),
        args=[req.model_id, None],
        id=job_id,
        name=f"爬虫模型_{req.model_id}",
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info(f"定时任务已设置：model_id={req.model_id} "
                f"cron={req.cron_hour}:{req.cron_minute}")
    return {
        "success": True,
        "job_id":  job_id,
        "cron":    f"{req.cron_hour}:{req.cron_minute}",
    }

@app.delete("/scheduler/remove/{model_id}")
def remove_schedule(model_id: int):
    """移除定时任务"""
    job_id = f"model_{model_id}"
    if not _scheduler.get_job(job_id):
        raise HTTPException(status_code=404, detail="定时任务不存在")
    _scheduler.remove_job(job_id)
    return {"success": True, "message": f"model_id={model_id} 定时任务已移除"}


@app.get("/scheduler/list")
def list_schedules():
    """查询所有定时任务"""
    return [
        {
            "job_id":   job.id,
            "name":     job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
            "trigger":  str(job.trigger),
        }
        for job in _scheduler.get_jobs()
    ]