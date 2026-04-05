"""
Scheduler：定时触发 Orchestrator。
使用 APScheduler，支持 cron 和 interval 两种模式。

pip install apscheduler
"""
from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from utils.logger import get_logger
from orchestrator.orchestrator import Orchestrator

logger = get_logger("Scheduler")

# ── 配置区 ────────────────────────────────────────────────
DB_URL       = "mysql+pymysql://root:Yxy201062@localhost:3306/ship_digital_db"
MODEL_IDS    = [1]          # 支持多个爬虫模型并发调度
SAMPLE_LIMIT = None         # 生产环境不限制
OUTPUT_DIR   = "data/output"
CRON_HOUR    = "2"          # 每天凌晨 2 点执行
CRON_MINUTE  = "0"


def run_model(model_id: int):
    logger.info(f"Scheduler 触发 | model_id={model_id}")
    try:
        ok = Orchestrator(
            db_url=DB_URL,
            model_id=model_id,
            sample_limit=SAMPLE_LIMIT,
            output_dir=OUTPUT_DIR,
        ).run()
        logger.info(f"model_id={model_id} {'成功' if ok else '终止'}")
    except Exception as e:
        logger.error(f"model_id={model_id} 异常：{e}", exc_info=True)


def main():
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    for mid in MODEL_IDS:
        scheduler.add_job(
            func=run_model,
            trigger=CronTrigger(hour=CRON_HOUR, minute=CRON_MINUTE),
            args=[mid],
            id=f"model_{mid}",
            name=f"爬虫模型_{mid}",
            max_instances=1,          # 防止重叠执行
            misfire_grace_time=300,   # 错过触发允许补跑 5 分钟内
        )
        logger.info(f"已注册：model_id={mid} | cron={CRON_HOUR}:{CRON_MINUTE}")

    logger.info("Scheduler 启动，等待触发...")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler 手动停止")


if __name__ == "__main__":
    main()