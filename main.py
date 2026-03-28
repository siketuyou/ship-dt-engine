"""
数字化转型信息数据库 - 爬虫引擎入口
用法:
    python main.py run          # 立即执行一次全量/增量采集
    python main.py schedule     # 启动定时调度守护进程
    python main.py test-fetch   # 测试单个采集器连通性
"""
import sys
import argparse
from utils.logger import get_logger

logger = get_logger(__name__)


def cmd_run(args):
    """立即触发一次采集流水线"""
    logger.info("=== 手动触发采集流水线 ===")
    # TODO Step-12: from orchestrator.pipeline import Pipeline; Pipeline().run()
    logger.info("[stub] pipeline.run() 尚未实现，请完成 orchestrator/pipeline.py")


def cmd_schedule(args):
    """启动定时调度守护进程"""
    logger.info("=== 启动定时调度器 ===")
    # TODO Step-13: from scheduler.task_runner import TaskRunner; TaskRunner().start()
    logger.info("[stub] scheduler 尚未实现，请完成 scheduler/task_runner.py")


def cmd_test_fetch(args):
    """测试采集器连通性（用于开发调试）"""
    logger.info("=== 测试采集器连通性 ===")
    # TODO Step-7: 逐个实例化 fetcher，调用 .ping() 方法
    logger.info("[stub] fetchers 尚未实现")


def main():
    parser = argparse.ArgumentParser(description="船舶数字化转型爬虫引擎")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("run", help="立即执行一次采集")
    subparsers.add_parser("schedule", help="启动定时调度")
    subparsers.add_parser("test-fetch", help="测试采集器")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "schedule":
        cmd_schedule(args)
    elif args.command == "test-fetch":
        cmd_test_fetch(args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()