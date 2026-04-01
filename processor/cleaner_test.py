
"""
集成测试入口：Fetcher → Filter → Cleaner
python tests/run_integration.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db_manager import DatabaseManager
from fetchers.csic.csic_fetcher import CsicFetcher
from processor.filter import ArticleFilter,FilteredItem
from processor.cleaner import ArticleCleaner 
from models.schemas import CleanedItem
from utils.logger import get_logger

logger = get_logger("integration_test")

DB_URL   = "mysql+pymysql://root:Yxy201062@localhost:3306/ship_digital_db"
MODEL_ID = 1


def main():
    logger.info("=" * 60)
    logger.info("集成测试：Fetcher → Filter → Cleaner")
    logger.info("=" * 60)

    # ── Step 1: 数据库 ──────────────────────────────────────
    logger.info("[1/5] 连接数据库...")
    db  = DatabaseManager(DB_URL)
    kws = db.get_keywords_by_model(MODEL_ID)
    if not kws:
        logger.error(f"model_id={MODEL_ID} 无活跃关键词")
        return
    logger.info(f"      关键词数={len(kws)}")
    for kw in kws:
        logger.info(f"      [{kw['keyword_id']}] {kw['keyword_name']}  水位线={kw['incremental_spider_time']}")

    # ── Step 2: Fetcher ─────────────────────────────────────
    logger.info("[2/5] 启动 CsicFetcher...")
    fetcher      = CsicFetcher(model_id=MODEL_ID, db_manager=db)
    raw_articles = fetcher.fetch_all()
    logger.info(f"      抓取完成，共 {len(raw_articles)} 篇")
    if not raw_articles:
        logger.warning("      Fetcher 返回空列表，终止")
        return
    logger.info("      --- 样本（前3条）---")
    for a in raw_articles[:3]:
        logger.info(f"      标题: {a.title}")
        logger.info(f"      URL : {a.url}")
        logger.info(f"      时间: {a.pub_time}")
        logger.info(f"      正文前80字: {(a.content or '')[:80]!r}")
        logger.info("")

    # ── Step 3: Filter ──────────────────────────────────────
    logger.info("[3/5] 启动 ArticleFilter...")
    f_filter  = ArticleFilter(model_id=MODEL_ID, db_manager=db)
    filtered  = f_filter.run(raw_articles)
    logger.info(f"      过滤完成：{len(raw_articles)} → {len(filtered)} 篇")
    if not filtered:
        logger.warning("      过滤后为空，终止")
        return

    # ── Step 4: Cleaner ─────────────────────────────────────
    logger.info("[4/5] 启动 ArticleCleaner...")
    cleaner = ArticleCleaner()
    cleaned = cleaner.run(filtered)
    logger.info(f"      清洗完成：{len(filtered)} → {len(cleaned)} 篇")

    # ── Step 5: 验证 & 打印 ──────────────────────────────────
    logger.info("[5/5] 结果验证...")

    _assert(all(isinstance(i, CleanedItem) for i in cleaned), "结果类型错误")
    _assert(all(i.url_fingerprint for i in cleaned),          "url_fingerprint 为空")
    _assert(all(i.title for i in cleaned),                    "title 为空")
    _assert(all(i.content for i in cleaned),                  "content 为空")
    _assert(all("<" not in i.content for i in cleaned),       "content 含残留 HTML 标签")

    logger.info("      所有断言通过 ✓")
    logger.info("")
    logger.info(f"      --- 清洗结果（共 {len(cleaned)} 篇，展示前3条）---")
    for item in cleaned[:3]:
        logger.info(f"      标题        : {item.title}")
        logger.info(f"      URL         : {item.url}")
        logger.info(f"      fingerprint : {item.url_fingerprint[:16]}...")
        logger.info(f"      时间        : {item.pub_time}")
        logger.info(f"      正文前100字 : {item.content[:100]!r}")
        logger.info("")

    logger.info("=" * 60)
    logger.info("cleaner集成测试完成")
    logger.info("=" * 60)


def _assert(cond: bool, msg: str):
    if not cond:
        logger.error(f"断言失败: {msg}")
        sys.exit(1)

if __name__ == "__main__":
    main()