from __future__ import annotations

from datetime import datetime
from typing import Optional

from apscheduler.triggers.cron import CronTrigger

from .deps import _db, _lock, _running_locks, _scheduler, OUTPUT_DIR
from utils.logger import get_logger
from orchestrator.orchestrator import Orchestrator

logger = get_logger("SpiderAPI")


def _update_state(model_id: int, state: str):
    try:
        _db.execute(
            "UPDATE reptile_model SET m_reptile_model_state=:state "
            "WHERE m_reptile_model_id=:id",
            {"state": state, "id": model_id},
        )
        logger.info(f"model_id={model_id} 状态 → {state}")
    except Exception as e:
        logger.error(f"状态更新失败：{e}")


def _write_run_log(model_id: int, run_state: str, result_desc: str, csv_path: Optional[str] = None):
    try:
        _db.execute(
            "INSERT INTO reptile_model_log "
            "(model_id, run_time, run_state, result_desc, csv_address, deleted) "
            "VALUES (:model_id, :run_time, :run_state, :result_desc, :csv_address, 0)",
            {
                "model_id":    model_id,
                "run_time":    datetime.now(),
                "run_state":   run_state,
                "result_desc": result_desc,
                "csv_address": csv_path or "",
            },
        )
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
