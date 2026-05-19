"""
对应的fetchid对应数据库爬虫模型id，如果是fetch_all需要按照最低水位线全量爬取RawArticle。fetch_keyword则按照对应关键词id查询水位线爬取RawArticle。抽象成具体aicoding指令
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime
from models.schemas import RawArticle
from utils.logger import get_logger

class BaseFetcher(ABC):
    def __init__(self, model_id: int, db_manager):
        self.model_id = model_id
        self.__db = db_manager          # name-mangled：子类无法通过 self.__db 访问
        self.config = self.__db.get_model_config(model_id)
        self.logger = get_logger(self.__class__.__name__)

    @abstractmethod
    def _run_spider(self, since_time: datetime) -> List[RawArticle]:
        pass

    # ── DB 访问统一封装，子类只能调这些方法，无法拿到 db 对象本身 ──────────

    def _load_watermark(self) -> Optional[datetime]:
        keywords_info = self.__db.get_keywords_by_model(self.model_id)
        if not keywords_info:
            return None
        return min(k["incremental_spider_time"] for k in keywords_info)

    def _filter_existing(self, articles: List[RawArticle]) -> List[RawArticle]:
        if not articles:
            return []
        urls = [a.url for a in articles]
        try:
            rows = self.__db.query_in(
                "SELECT device_news_link FROM device"
                " WHERE device_news_link IN :urls",
                {"urls": urls},
            )
            existing = {r["device_news_link"] for r in rows}
        except Exception as e:
            self.logger.warning(f"DB URL 查重失败，跳过过滤继续执行：{e}")
            return articles
        filtered = [a for a in articles if a.url not in existing]
        skipped = len(articles) - len(filtered)
        if skipped:
            self.logger.info(f"DB 查重过滤 {skipped} 条已入库文章，剩余 {len(filtered)} 条进入推理")
        return filtered

    # ── 批次内去重 ────────────────────────────────────────────────────────

    def _deduplicate_raw(self, articles: List[RawArticle]) -> List[RawArticle]:
        seen: set = set()
        return [a for a in articles if not (a.url in seen or seen.add(a.url))]

    # ── 默认 fetch_all：适用于不需要两阶段的简单子类 ─────────────────────

    def fetch_all(self) -> List[RawArticle]:
        watermark = self._load_watermark()
        if watermark is None:
            return []
        all_results = self._run_spider(watermark)
        all_results = self._deduplicate_raw(all_results)
        return self._filter_existing(all_results)

