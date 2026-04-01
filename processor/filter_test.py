"""
集成测试入口，直接 python tests/run_integration.py 运行。
无需设置环境变量，数据库连接硬编码在 Settings 中。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # processor/ 的上级
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db_manager import DatabaseManager
from fetchers.csic.csic_fetcher import CsicFetcher
from processor.filter import ArticleFilter
from models.schemas import FilteredItem
from utils.logger import get_logger

logger = get_logger("integration_test")

# ── 数据库连接 ──────────────────────────────────────────────
DB_URL = "mysql+pymysql://root:Yxy201062@localhost:3306/ship_digital_db"
MODEL_ID = 1


def main():
    logger.info("=" * 60)
    logger.info("集成测试开始：Fetcher → Filter")
    logger.info("=" * 60)

    # ── Step 1: 初始化数据库 ────────────────────────────────
    logger.info("[1/4] 连接数据库...")
    db = DatabaseManager(DB_URL)

    kws = db.get_keywords_by_model(MODEL_ID)
    if not kws:
        logger.error(f"model_id={MODEL_ID} 无活跃关键词，请检查数据库配置")
        return

    logger.info(f"      关键词数={len(kws)}")
    for kw in kws:
        logger.info(f"      [{kw['keyword_id']}] {kw['keyword_name']}  水位线={kw['incremental_spider_time']}")

    # ── Step 2: Fetcher ─────────────────────────────────────
    logger.info("[2/4] 启动 CsicFetcher...")
    fetcher = CsicFetcher(model_id=MODEL_ID, db_manager=db)
    raw_articles = fetcher.fetch_all()

    logger.info(f"      抓取完成，共 {len(raw_articles)} 篇")
    if not raw_articles:
        logger.warning("      Fetcher 返回空列表，终止测试")
        return

    # 打印前 3 条 fetcher 输出
    logger.info("      --- Fetcher 样本（前3条）---")
    for a in raw_articles[:3]:
        logger.info(f"      标题  : {a.title}")
        logger.info(f"      URL   : {a.url}")
        logger.info(f"      时间  : {a.pub_time}")
        logger.info(f"      正文前80字: {(a.content or '')[:80]!r}")
        logger.info("")

    # ── Step 3: Filter ──────────────────────────────────────
    logger.info("[3/4] 启动 ArticleFilter...")
    article_filter = ArticleFilter(model_id=MODEL_ID, db_manager=db)
    filtered = article_filter.run(raw_articles)

    logger.info(f"      过滤完成：{len(raw_articles)} → {len(filtered)} 篇")

    # ── Step 4: 结果验证 & 打印 ─────────────────────────────
    logger.info("[4/4] 结果验证...")

    _assert(len(filtered) <= len(raw_articles), "过滤后数量不应超过原始数量")
    _assert(
        all(isinstance(i, FilteredItem) for i in filtered),
        "所有结果应为 FilteredItem"
    )
    _assert(
        all(i.matched_keyword_ids for i in filtered),
        "所有 FilteredItem 应有非空 matched_keyword_ids"
    )

    raw_urls = {a.url for a in raw_articles}
    for item in filtered:
        _assert(item.article.url in raw_urls, f"出现未知 URL: {item.article.url}")

    valid_ids = {kw["keyword_id"] for kw in kws}
    for item in filtered:
        for kid in item.matched_keyword_ids:
            _assert(kid in valid_ids, f"keyword_id={kid} 不存在于数据库")

    logger.info("      所有断言通过 ✓")
    logger.info("")
    logger.info(f"      --- Filter 结果（共 {len(filtered)} 篇，展示前5条）---")
    for item in filtered[:5]:
        a = item.article
        logger.info(f"      标题   : {a.title}")
        logger.info(f"      URL    : {a.url}")
        logger.info(f"      时间   : {a.pub_time}")
        logger.info(f"      命中词 : {item.matched_keyword_ids}")
        logger.info(f"      正文前80字: {(a.content or '')[:80]!r}")
        logger.info("")

    logger.info("=" * 60)
    logger.info("集成测试完成")
    logger.info("=" * 60)


def _assert(condition: bool, msg: str):
    if not condition:
        logger.error(f"断言失败: {msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()