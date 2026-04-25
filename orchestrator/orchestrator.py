"""
Orchestrator：单次完整流水线执行。
Fetcher → Filter → Cleaner → Dedup → Extractor → CsvWriter

被 Scheduler 调用，也可单独运行。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]  # 上两级 = ship_digital_python/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from datetime import datetime
from typing import Optional

from storage.db_manager import DatabaseManager
from storage.csv_writer import CsvWriter
from storage.csv_importer import CsvImporter
from fetchers.load_fetcher import load_fetcher
from processor.filter import ArticleFilter
from processor.cleaner import ArticleCleaner
from processor.dedup_engine import DedupEngine
from processor.extractor import Extractor
from utils.logger import get_logger
from config.settings import settings
logger = get_logger("Orchestrator")


class Orchestrator:

    def __init__(
        self,
        model_id: int,
        db_url: str = "",
        db_manager=None,
        sample_limit: Optional[int] = None,
        output_dir: str = "data/output",
        user_id: int = 0,
        auto_import: bool = False,
    ):
        self.model_id     = model_id
        self.sample_limit = sample_limit
        self.user_id      = user_id
        self.db           = db_manager if db_manager is not None else DatabaseManager(db_url)
        self.csv_writer   = CsvWriter(output_dir)
        self.auto_import  = auto_import
        self.filter = ArticleFilter(model_id=model_id, db_manager=self.db)
    def run(self) -> tuple[bool, str, Optional[str]]:
        """
        执行完整流水线。
        返回 (ok, result_desc, csv_path)：
          ok          — True=成功，False=中途终止
          result_desc — 人类可读的结果说明（含错误原因）
          csv_path    — 成功时的 CSV 路径，否则 None
        """
        start = datetime.now()
        logger.info("=" * 60)
        logger.info(f"Orchestrator 启动 | model_id={self.model_id} | {start}")
        logger.info("=" * 60)

        # ── Step 1: 关键词校验 ───────────────────────────────
        kws = self.db.get_keywords_by_model(self.model_id)
        if not kws:
            msg = f"model_id={self.model_id} 无活跃关键词，终止"
            logger.error(msg)
            return False, msg, None
        logger.info(f"[1] 关键词={len(kws)} 个")

        # ── Step 2: Fetcher ──────────────────────────────────
        model_config = self.db.get_model_config(self.model_id)
        model_name = model_config["model_name"]
        fetcher = load_fetcher(
            model_name=model_name,
            model_id=self.model_id,
            db_manager=self.db,
        )
        raw_articles = fetcher.fetch_all()
        logger.info(f"[2] Fetcher 完成：{len(raw_articles)} 篇")
        if not raw_articles:
            msg = "Fetcher 返回空，无新数据，终止"
            logger.warning(msg)
            return False, msg, None

        # ── Step 3: Filter ───────────────────────────────────
        filtered = self.filter.run(raw_articles)
        logger.info(f"[3] Filter 完成：{len(raw_articles)} → {len(filtered)} 篇")
        if not filtered:
            msg = f"Filter 后为空（原始 {len(raw_articles)} 篇全部过滤），终止"
            logger.warning(msg)
            return False, msg, None

        # ── Step 4: Cleaner ──────────────────────────────────
        cleaned = ArticleCleaner().run(filtered)
        logger.info(f"[4] Cleaner 完成：{len(filtered)} → {len(cleaned)} 篇")

        # ── Step 5: Dedup ────────────────────────────────────
        deduped = DedupEngine().run(cleaned)
        logger.info(f"[5] Dedup 完成：{len(cleaned)} → {len(deduped)} 篇")

        # ── Step 6: Extractor ────────────────────────────────
        sample = deduped[: self.sample_limit] if self.sample_limit else deduped
        logger.info(f"[6] Extractor 启动，样本数={len(sample)}")

        raw_conn = self.db.get_raw_conn() if hasattr(self.db, "get_raw_conn") else None
        enriched = []
        csv_path = None
        try:
            enriched = Extractor(db_conn=raw_conn).run(sample)
            logger.info(f"[6] Extractor 完成：{len(sample)} → {len(enriched)} 条")

            if not enriched:
                msg = "Extractor 输出为空，终止"
                logger.error(msg)
                return False, msg, None

            # ── Step 7: CsvWriter ────────────────────────────────
            kw_names = [kw["keyword_name"] for kw in kws]

            csv_path = self.csv_writer.write(
                items=enriched,
                model_id=self.model_id,
                model_name=kws[0].get("model_name", str(self.model_id)) if kws else str(self.model_id),
                keywords=kw_names,
                total_fetched=len(raw_articles),
                total_filtered=len(filtered),
                total_input=len(sample),
                db_conn=raw_conn,
                user_id=self.user_id,
            )
            logger.info(f"[7] CSV 已输出：{csv_path}")

            # ── Step 8: CsvImporter（自动入库） ──────────────────
            if self.auto_import:
                logger.info(f"[8] 开始自动入库：{csv_path}")
                try:
                    result = CsvImporter(raw_conn).run(
                        csv_path=csv_path,
                        model_log_id=self.model_id,
                        user_id=self.user_id,
                    )
                    logger.info(
                        f"[8] 入库完成：总={result['total']} "
                        f"成功={result['success']} 失败={result['failed']}"
                    )
                    if result["errors"]:
                        for err in result["errors"][:10]:
                            logger.warning(f"  入库错误：{err}")
                except Exception as e:
                    logger.error(f"[8] 自动入库异常：{e}", exc_info=True)
            else:
                logger.info("[8] 跳过自动入库，CSV 已保存供手动录入")
        finally:
            if raw_conn:
                raw_conn.close()

        elapsed = (datetime.now() - start).seconds
        msg = f"流水线完成，产出 {len(enriched)} 条，耗时 {elapsed}s，CSV={csv_path}"
        logger.info(msg)
        logger.info("=" * 60)
        return True, msg, str(csv_path) if csv_path else None
# orchestrator.py 底部添加

if __name__ == "__main__":
    import sys
    from pathlib import Path

    PROJECT_ROOT = Path(__file__).resolve().parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    # ── 测试配置 ──────────────────────────────────────────
    DB_URL = settings.db_url
    MODEL_ID     = 1
    SAMPLE_LIMIT = 9       # 先只跑 9 条，验证流程通
    OUTPUT_DIR   = "data/output"

    print("=" * 60)
    print("Orchestrator 单元测试")
    print("=" * 60)

    ok, msg, csv_path = Orchestrator(
        model_id=MODEL_ID,
        db_url=DB_URL,
        sample_limit=SAMPLE_LIMIT,
        output_dir=OUTPUT_DIR,
    ).run()

    print("=" * 60)
    print(f"结果：{'✅ 成功' if ok else '❌ 失败'}")
    print(f"说明：{msg}")
    if csv_path:
        print(f"CSV：{csv_path}")
    print("=" * 60)