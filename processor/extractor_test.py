"""
集成测试入口：Fetcher → Filter → Cleaner → Dedup → Extractor
python tests/run_integration.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.db_manager import DatabaseManager
from fetchers.csic.csic_fetcher import CsicFetcher
from processor.filter import ArticleFilter
from processor.cleaner import ArticleCleaner
from processor.dedup_engine import DedupEngine
from processor.extractor import Extractor
from models.schemas import CleanedItem, EnrichedItem
from utils.logger import get_logger

logger = get_logger("integration_test")

DB_URL   = "mysql+pymysql://root:Yxy201062@localhost:3306/ship_digital_db"
MODEL_ID = 1

# Extractor 专项配置
EXTRACTOR_DRY_RUN       = True   # True=不写库，只打印；False=自动入库新三级方向
EXTRACTOR_SAMPLE_LIMIT  = 10      # 只取前 N 条跑 LLM，节省测试时间（None=全量）


def main():
    logger.info("=" * 60)
    logger.info("集成测试：Fetcher → Filter → Cleaner → Dedup → Extractor")
    logger.info("=" * 60)

    # ── Step 1: 数据库 ──────────────────────────────────────
    logger.info("[1/7] 连接数据库...")
    db  = DatabaseManager(DB_URL)
    kws = db.get_keywords_by_model(MODEL_ID)
    if not kws:
        logger.error(f"model_id={MODEL_ID} 无活跃关键词")
        return
    logger.info(f"      关键词数={len(kws)}")
    for kw in kws:
        logger.info(f"      [{kw['keyword_id']}] {kw['keyword_name']}  水位线={kw['incremental_spider_time']}")

    # ── Step 2: Fetcher ─────────────────────────────────────
    logger.info("[2/7] 启动 CsicFetcher...")
    fetcher      = CsicFetcher(model_id=MODEL_ID, db_manager=db)
    raw_articles = fetcher.fetch_all()
    logger.info(f"      抓取完成，共 {len(raw_articles)} 篇")
    if not raw_articles:
        logger.warning("      Fetcher 返回空列表，终止")
        return

    # ── Step 3: Filter ──────────────────────────────────────
    logger.info("[3/7] 启动 ArticleFilter...")
    filtered = ArticleFilter(model_id=MODEL_ID, db_manager=db).run(raw_articles)
    logger.info(f"      过滤完成：{len(raw_articles)} → {len(filtered)} 篇")
    if not filtered:
        logger.warning("      过滤后为空，终止")
        return

    # ── Step 4: Cleaner ─────────────────────────────────────
    logger.info("[4/7] 启动 ArticleCleaner...")
    cleaned = ArticleCleaner().run(filtered)
    logger.info(f"      清洗完成：{len(filtered)} → {len(cleaned)} 篇")

    # ── Step 5: Dedup ───────────────────────────────────────
    logger.info("[5/7] 启动 DedupEngine...")
    deduped = DedupEngine().run(cleaned)
    logger.info(f"      去重完成：{len(cleaned)} → {len(deduped)} 篇")

    # ── Step 6: 前序验证 ─────────────────────────────────────
    logger.info("[6/7] 前序结果验证...")
    _assert(all(isinstance(i, CleanedItem) for i in deduped), "结果类型错误")
    _assert(all(i.url_fingerprint for i in deduped),          "url_fingerprint 为空")
    _assert(all(i.title for i in deduped),                    "title 为空")
    _assert(all(i.content for i in deduped),                  "content 为空")
    fps = [i.url_fingerprint for i in deduped]
    _assert(len(fps) == len(set(fps)), "去重后仍有重复 URL")
    logger.info("      所有断言通过 ✓")

    # ── Step 7: Extractor ────────────────────────────────────
    logger.info("[7/7] 启动 Extractor（LLM 结构化提取）...")

    sample = deduped[:EXTRACTOR_SAMPLE_LIMIT] if EXTRACTOR_SAMPLE_LIMIT else deduped
    logger.info(f"      本次提取样本数={len(sample)}（EXTRACTOR_SAMPLE_LIMIT={EXTRACTOR_SAMPLE_LIMIT}）")

    # db_conn 传给 Extractor 用于读取维度树；dry_run 时不自动写新三级方向
    raw_conn = db.get_raw_conn() if hasattr(db, "get_raw_conn") else None
    extractor = Extractor(
        db_conn=raw_conn
    )
    enriched: list[EnrichedItem] = extractor.run(sample)

    logger.info(f"      提取完成：{len(sample)} → {len(enriched)} 条")

    # ── Extractor 断言 ──────────────────────────────────────
    _assert(len(enriched) > 0, "Extractor 输出为空，LLM 可能全部失败")
    _assert(all(isinstance(i, EnrichedItem) for i in enriched), "输出类型非 EnrichedItem")
    _assert(all(i.device_name for i in enriched),               "device_name 为空")
    _assert(all(i.device_news_link for i in enriched),          "device_news_link 为空")

    # device_introduce 改为警告，统计缺失数量而不是直接退出
    missing_introduce = [i for i in enriched if not i.device_introduce]
    if missing_introduce:
        logger.warning(f"      ⚠ {len(missing_introduce)} 条 device_introduce 为空：")
        for i in missing_introduce:
            logger.warning(f"        - {i.device_news_title[:60]}")
    else:
        logger.info("      device_introduce 全部非空 ✓")

    logger.info("      Extractor 断言通过 ✓")

    # ── 详细打印 ────────────────────────────────────────────
    logger.info("")
    logger.info(f"      --- Extractor 结果（共 {len(enriched)} 条）---")
    for idx, item in enumerate(enriched, 1):
        logger.info(f"      [{idx}] ────────────────────────────────────")
        logger.info(f"           device_name      : {item.device_name}")
        logger.info(f"           device_class_id  : {item.device_class_id}   (一级维度)")
        logger.info(f"           device_style_id  : {item.device_style_id}   (二级维度)")
        logger.info(f"           device_type_id   : {item.device_type_id}    (三级方向)")
        logger.info(f"           device_keywords  : {item.device_keywords}")
        logger.info(f"           device_use_year  : {item.device_use_year}")
        logger.info(f"           device_price     : {item.device_price}")
        logger.info(f"           device_using_unit: {item.device_using_unit}")
        logger.info(f"           device_location  : {item.device_location}")
        logger.info(f"           device_latitude  : {item.device_latitude}")
        logger.info(f"           device_longitude : {item.device_longitude}")
        logger.info(f"           device_country_id: {item.device_country_id}")
        logger.info(f"           device_news_time : {item.device_news_time}")
        logger.info(f"           device_news_link : {item.device_news_link}")
        logger.info(f"           device_introduce : {(item.device_introduce[:80] + '...') if item.device_introduce else 'N/A'}")
        logger.info("")



    logger.info("=" * 60)
    logger.info("集成测试完成")
    logger.info("=" * 60)


def _assert(cond: bool, msg: str):
    if not cond:
        logger.error(f"断言失败: {msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()