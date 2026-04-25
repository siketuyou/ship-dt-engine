# api/main.py
from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from orchestrator.orchestrator import Orchestrator
from storage.db_manager import DatabaseManager
from storage.csv_importer import CsvImporter
from utils.logger import get_logger
from config.settings import settings

logger = get_logger("SpiderAPI")

app = FastAPI(title="Spider Service")

# ================================================================
# CORS
# ================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================================================================
# 配置 & 全局单例
# ================================================================
DB_URL     = settings.db_url
OUTPUT_DIR = "data/output"
UPLOAD_DIR = Path("data/upload")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 单例：整个进程共享同一个连接池
_db = DatabaseManager(DB_URL)

# 新关键词默认增量时间（足够早，确保全量抓取）
DEFAULT_INCREMENTAL_TIME = "2000-01-01 00:00:00"

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
_scheduler.start()

_running_locks: dict[int, bool] = {}
_lock = threading.Lock()


# ================================================================
# 统一响应格式
# ================================================================
def ok(data=None, message="success"):
    return {"code": 200, "message": message, "data": data}

def fail(message="failed", code=500):
    return {"code": code, "message": message, "data": None}


# ================================================================
# Schema
# ================================================================
class KeywordCreateBody(BaseModel):
    modelId: int
    keywordName: str
    useFlag: int = 1


# ================================================================
# 工具函数
# ================================================================
def _update_state(model_id: int, state: str):
    try:
        with _db.raw_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE reptile_model SET m_reptile_model_state=%s "
                "WHERE m_reptile_model_id=%s",
                (state, model_id),
            )
            conn.commit()
            cursor.close()
        logger.info(f"model_id={model_id} 状态 → {state}")
    except Exception as e:
        logger.error(f"状态更新失败：{e}")


# ================================================================
# 模型管理
# ================================================================

# ── GET /api/model/list ──────────────────────────────────
@app.get("/api/model/list")
def get_model_list(
    pageNum:  int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
):
    offset = (pageNum - 1) * pageSize
    with _db.raw_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM reptile_model WHERE deleted=0")
        total = (cursor.fetchone() or (0,))[0]
        cursor.execute(
            """
            SELECT m_reptile_model_id, m_reptile_model_name,
                   m_reptile_model_introduce, m_reptile_model_web,
                   m_reptile_model_state, m_reptile_model_time
            FROM reptile_model
            WHERE deleted=0
            ORDER BY m_reptile_model_id DESC
            LIMIT %s OFFSET %s
            """,
            (pageSize, offset),
        )
        rows = cursor.fetchall()
        cursor.close()

    records = [
        {
            "mReptileModelId":        r[0],
            "mReptileModelName":      r[1],
            "mReptileModelIntroduce": r[2],
            "mReptileModelWeb":       r[3],
            "mReptileModelState":     r[4],
            "mReptileModelTime":      str(r[5]) if r[5] else "",
        }
        for r in rows
    ]
    return ok({"records": records, "total": total})


# ── GET /api/model/{id} ──────────────────────────────────
@app.get("/api/model/{model_id}")
def get_model_detail(model_id: int):
    with _db.raw_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT m_reptile_model_id,
                   m_reptile_model_name,
                   m_reptile_model_introduce,
                   m_reptile_model_web,
                   m_reptile_model_state,
                   m_reptile_model_time,
                   m_reptile_model_script_address,
                   m_reptile_model_address,
                   cron_expression
            FROM reptile_model
            WHERE m_reptile_model_id=%s AND deleted=0
            """,
            (model_id,),
        )
        row = cursor.fetchone()
        if not row:
            cursor.close()
            raise HTTPException(status_code=404, detail="模型不存在")

        cursor.execute(
            """
            SELECT keyword_id, keyword_name, use_flag, incremental_spider_time
            FROM keyword
            WHERE model_id=%s AND deleted=0
            ORDER BY keyword_id ASC
            """,
            (model_id,),
        )
        kw_rows = cursor.fetchall()
        cursor.close()

    return ok({
        "mReptileModelId":            row[0],
        "mReptileModelName":          row[1],
        "mReptileModelIntroduce":     row[2],
        "mReptileModelWeb":           row[3],
        "mReptileModelState":         row[4],
        "mReptileModelTime":          str(row[5]) if row[5] else "",
        "mReptileModelScriptAddress": row[6],
        "mReptileModelAddress":       row[7],
        "cronExpression":             row[8] or "",
        "keywords": [
            {
                "keywordId":             k[0],
                "keywordName":           k[1],
                "useFlag":               k[2],
                "incrementalSpiderTime": str(k[3]) if k[3] else "",
            }
            for k in kw_rows
        ],
    })


# ── POST /api/model/save ─────────────────────────────────
@app.post("/api/model/save")
async def save_model(
    mReptileModelId:        Optional[str]        = Form(None),
    mReptileModelName:      str                  = Form(...),
    mReptileModelIntroduce: str                  = Form(""),
    mReptileModelWeb:       str                  = Form(...),
    cronExpression:         str                  = Form(""),
    keywords:               str                  = Form("[]"),
    scriptFile:             Optional[UploadFile] = File(None),
    startupFile:            Optional[UploadFile] = File(None),
):
    """
    新增 / 编辑模型（FormData 含文件上传）

    关键词同步逻辑（差量）：
      - 传回 keywordId  → UPDATE（名称 / useFlag / 增量时间）
      - 未传 keywordId  → INSERT 新记录
      - 库中有但前端未传回的 keywordId → deleted=1 逻辑删除
    """
    model_id = int(mReptileModelId) if mReptileModelId else None
    kw_list: List[dict] = json.loads(keywords) if keywords else []

    # ── 保存上传文件 ─────────────────────────────────────
    script_path  = ""
    startup_path = ""

    if scriptFile and scriptFile.filename:
        p = UPLOAD_DIR / f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{scriptFile.filename}"
        with open(p, "wb") as f:
            shutil.copyfileobj(scriptFile.file, f)
        script_path = str(p)

    if startupFile and startupFile.filename:
        p = UPLOAD_DIR / f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{startupFile.filename}"
        with open(p, "wb") as f:
            shutil.copyfileobj(startupFile.file, f)
        startup_path = str(p)

    try:
        with _db.raw_conn() as conn:
            cursor = conn.cursor()
            try:
                # ── 判断新增 / 编辑 ───────────────────────────
                is_edit = False
                if model_id:
                    cursor.execute(
                        "SELECT m_reptile_model_id FROM reptile_model "
                        "WHERE m_reptile_model_id=%s AND deleted=0",
                        (model_id,),
                    )
                    is_edit = cursor.fetchone() is not None

                if is_edit:
                    cursor.execute(
                        """
                        UPDATE reptile_model SET
                            m_reptile_model_name=%s,
                            m_reptile_model_introduce=%s,
                            m_reptile_model_web=%s,
                            cron_expression=%s
                            {script_col}
                            {startup_col}
                        WHERE m_reptile_model_id=%s AND deleted=0
                        """.format(
                            script_col=", m_reptile_model_script_address=%s" if script_path else "",
                            startup_col=", m_reptile_model_address=%s"        if startup_path else "",
                        ),
                        (
                            mReptileModelName,
                            mReptileModelIntroduce,
                            mReptileModelWeb,
                            cronExpression or None,
                            *([script_path]  if script_path  else []),
                            *([startup_path] if startup_path else []),
                            model_id,
                        ),
                    )

                    # 差量同步关键词
                    incoming_ids = {
                        int(kw["keywordId"])
                        for kw in kw_list
                        if kw.get("keywordId")
                    }
                    if incoming_ids:
                        placeholders = ",".join(["%s"] * len(incoming_ids))
                        cursor.execute(
                            f"""
                            UPDATE keyword SET deleted=1
                            WHERE model_id=%s
                              AND keyword_id NOT IN ({placeholders})
                              AND deleted=0
                            """,
                            (model_id, *incoming_ids),
                        )
                    else:
                        cursor.execute(
                            "UPDATE keyword SET deleted=1 WHERE model_id=%s AND deleted=0",
                            (model_id,),
                        )

                    for kw in kw_list:
                        kid       = kw.get("keywordId")
                        name      = kw.get("keywordName", "").strip()
                        use_flag  = kw.get("useFlag", 1)
                        incr_time = kw.get("incrementalSpiderTime") or DEFAULT_INCREMENTAL_TIME
                        if not name:
                            continue
                        if kid:
                            cursor.execute(
                                """
                                UPDATE keyword SET
                                    keyword_name=%s,
                                    use_flag=%s,
                                    incremental_spider_time=%s,
                                    deleted=0
                                WHERE keyword_id=%s AND model_id=%s
                                """,
                                (name, use_flag, incr_time, int(kid), model_id),
                            )
                        else:
                            cursor.execute(
                                """
                                INSERT INTO keyword
                                    (model_id, keyword_name, incremental_spider_time,
                                     use_flag, deleted)
                                VALUES (%s, %s, %s, %s, 0)
                                """,
                                (model_id, name, incr_time, use_flag),
                            )

                else:
                    cursor.execute(
                        """
                        INSERT INTO reptile_model
                            (m_reptile_model_name, m_reptile_model_introduce,
                             m_reptile_model_web, m_reptile_model_state,
                             m_reptile_model_script_address, m_reptile_model_address,
                             cron_expression, deleted)
                        VALUES (%s, %s, %s, 'stopped', %s, %s, %s, 0)
                        """,
                        (
                            mReptileModelName,
                            mReptileModelIntroduce,
                            mReptileModelWeb,
                            script_path,
                            startup_path,
                            cronExpression or None,
                        ),
                    )
                    model_id = cursor.lastrowid

                    for kw in kw_list:
                        name      = kw.get("keywordName", "").strip()
                        use_flag  = kw.get("useFlag", 1)
                        incr_time = kw.get("incrementalSpiderTime") or DEFAULT_INCREMENTAL_TIME
                        if not name:
                            continue
                        cursor.execute(
                            """
                            INSERT INTO keyword
                                (model_id, keyword_name, incremental_spider_time,
                                 use_flag, deleted)
                            VALUES (%s, %s, %s, %s, 0)
                            """,
                            (model_id, name, incr_time, use_flag),
                        )

                conn.commit()
            except Exception as e:
                logger.error(f"保存模型失败：{e}", exc_info=True)
                return fail(f"保存失败：{e}")
            finally:
                cursor.close()
    except Exception as e:
        return fail(f"保存失败：{e}")

    if cronExpression and model_id is not None:
        _register_cron(model_id, cronExpression)

    return ok({"mReptileModelId": model_id}, "保存成功")


# ── DELETE /api/model/{id} ───────────────────────────────
@app.delete("/api/model/{model_id}")
def delete_model(model_id: int):
    with _db.raw_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE reptile_model SET deleted=1 WHERE m_reptile_model_id=%s",
            (model_id,),
        )
        conn.commit()
        cursor.close()
    return ok(message="删除成功")


# ── POST /api/model/{id}/start ───────────────────────────
@app.post("/api/model/{model_id}/start")
def start_model(model_id: int):
    with _lock:
        if _running_locks.get(model_id):
            return fail(f"model_id={model_id} 已在运行中", code=409)
        _running_locks[model_id] = True

    threading.Thread(
        target=_run_pipeline,
        args=(model_id, None),
        daemon=True,
    ).start()
    return ok(message="启动成功")


# ── POST /api/model/{id}/stop ────────────────────────────
@app.post("/api/model/{model_id}/stop")
def stop_model(model_id: int):
    _update_state(model_id, "stopped")
    with _lock:
        _running_locks[model_id] = False
    return ok(message="停止成功")


# ================================================================
# 运行日志
# ================================================================

@app.get("/api/model/logs")
def get_run_logs(
    modelId:  int           = Query(...),
    state:    Optional[str] = Query(None),
    pageNum:  int           = Query(1, ge=1),
    pageSize: int           = Query(10, ge=1, le=100),
):
    where = "WHERE model_id=%s AND deleted=0"
    args: list = [modelId]
    if state:
        where += " AND run_state=%s"
        args.append(state)

    offset = (pageNum - 1) * pageSize
    with _db.raw_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM reptile_model_log {where}", args)
        total = (cursor.fetchone() or (0,))[0]
        cursor.execute(
            f"""
            SELECT log_id, run_time, run_state, result_desc,
                   csv_address, entry_state, entry_time
            FROM reptile_model_log {where}
            ORDER BY run_time DESC
            LIMIT %s OFFSET %s
            """,
            [*args, pageSize, offset],
        )
        rows = cursor.fetchall()
        cursor.close()

    records = [
        {
            "logId":      r[0],
            "runTime":    str(r[1]) if r[1] else "",
            "runState":   r[2],
            "resultDesc": r[3],
            "csvAddress": r[4],
            "entryState": r[5],
            "entryTime":  str(r[6]) if r[6] else "",
        }
        for r in rows
    ]
    return ok({"records": records, "total": total})


@app.delete("/api/model/{model_id}/logs")
def clear_run_logs(model_id: int):
    with _db.raw_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE reptile_model_log SET deleted=1 WHERE model_id=%s",
            (model_id,),
        )
        conn.commit()
        cursor.close()
    return ok(message="清空成功")


# ================================================================
# CSV 操作
# ================================================================

@app.post("/api/model/import-csv")
async def import_csv(
    file:   UploadFile = File(...),
    logId:  int        = Form(...),
    userId: int        = Form(0),
):
    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = UPLOAD_DIR / f"{ts}_{file.filename}"

    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        with _db.raw_conn() as conn:
            result = CsvImporter(conn).run(
                csv_path=save_path,
                model_log_id=logId,
                user_id=userId,
            )
    except Exception as e:
        logger.error(f"CSV 导入异常：{e}", exc_info=True)
        return fail(f"导入失败：{e}")

    return ok(result, "导入成功")


@app.get("/api/model/download-csv")
def download_csv(filePath: str = Query(...)):
    path = Path(filePath)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path=path, media_type="text/csv", filename=path.name)


# ================================================================
# 关键词管理（独立接口）
# ================================================================

@app.get("/api/model/{model_id}/keywords")
def get_keywords(model_id: int):
    with _db.raw_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT keyword_id, keyword_name, use_flag, incremental_spider_time
            FROM keyword WHERE model_id=%s AND deleted=0
            ORDER BY keyword_id ASC
            """,
            (model_id,),
        )
        rows = cursor.fetchall()
        cursor.close()
    return ok([
        {
            "keywordId":             r[0],
            "keywordName":           r[1],
            "useFlag":               r[2],
            "incrementalSpiderTime": str(r[3]) if r[3] else "",
        }
        for r in rows
    ])


@app.post("/api/model/keyword")
def add_keyword(body: KeywordCreateBody):
    with _db.raw_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO keyword
                (model_id, keyword_name, incremental_spider_time, use_flag, deleted)
            VALUES (%s, %s, %s, %s, 0)
            """,
            (body.modelId, body.keywordName, DEFAULT_INCREMENTAL_TIME, body.useFlag),
        )
        conn.commit()
        keyword_id = cursor.lastrowid
        cursor.close()
    return ok({"keywordId": keyword_id}, "添加成功")


@app.delete("/api/model/keyword/{keyword_id}")
def delete_keyword(keyword_id: int):
    with _db.raw_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE keyword SET deleted=1 WHERE keyword_id=%s",
            (keyword_id,),
        )
        conn.commit()
        cursor.close()
    return ok(message="删除成功")


# ================================================================
# 爬虫执行流水线
# ================================================================

def _write_run_log(model_id: int, run_state: str, result_desc: str, csv_path: Optional[str] = None):
    """将一次流水线执行结果写入 reptile_model_log。"""
    try:
        with _db.raw_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO reptile_model_log
                    (model_id, run_time, run_state, result_desc, csv_address, deleted)
                VALUES (%s, %s, %s, %s, %s, 0)
                """,
                (model_id, datetime.now(), run_state, result_desc, csv_path or ""),
            )
            conn.commit()
            cursor.close()
    except Exception as e:
        logger.error(f"写入运行日志失败：{e}")


def _run_pipeline(model_id: int, sample_limit: Optional[int]):
    try:
        _update_state(model_id, "running")
        ok_flag, result_desc, csv_path = Orchestrator(
            db_manager=_db,
            model_id=model_id,
            sample_limit=sample_limit,
            output_dir=OUTPUT_DIR,
        ).run()
        final_state = "stopped" if ok_flag else "error"
        _update_state(model_id, final_state)
        _write_run_log(model_id, final_state, result_desc, csv_path)
    except Exception as e:
        err_msg = f"流水线异常：{e}"
        logger.error(f"model_id={model_id} {err_msg}", exc_info=True)
        _update_state(model_id, "error")
        _write_run_log(model_id, "error", err_msg)
    finally:
        with _lock:
            _running_locks[model_id] = False


# ================================================================
# Cron 定时任务
# ================================================================

def _register_cron(model_id: int, cron_expr: str):
    job_id = f"model_{model_id}"
    try:
        parts = cron_expr.strip().split()
        if len(parts) == 6:
            second, minute, hour, day, month, day_of_week = parts
        elif len(parts) == 5:
            second = "0"
            minute, hour, day, month, day_of_week = parts
        else:
            logger.warning(f"Cron 表达式格式不正确：{cron_expr}")
            return

        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)

        _scheduler.add_job(
            func=_run_pipeline,
            trigger=CronTrigger(
                second=second, minute=minute, hour=hour,
                day=day, month=month, day_of_week=day_of_week,
            ),
            args=[model_id, None],
            id=job_id,
            name=f"爬虫模型_{model_id}",
            max_instances=1,
            misfire_grace_time=300,
        )
        logger.info(f"定时任务注册成功：model_id={model_id} cron={cron_expr}")
    except Exception as e:
        logger.error(f"定时任务注册失败：{e}")
