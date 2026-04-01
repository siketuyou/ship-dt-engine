"""
对应的fetchid对应数据库爬虫模型id，如果是fetch_all需要按照最低水位线全量爬取RawArticle。fetch_keyword则按照对应关键词id查询水位线爬取RawArticle。抽象成具体aicoding指令
"""
from abc import ABC, abstractmethod
from typing import List
from datetime import datetime
from models.schemas import RawArticle
from utils.logger import get_logger # L2 模型

class BaseFetcher(ABC):
    def __init__(self, model_id: int, db_manager):
        self.model_id = model_id
        self.db = db_manager
        # 从表 9 加载基础配置 (L1/L4)
        self.config = self.db.get_model_config(model_id) 
        self.logger = get_logger(self.__class__.__name__)

    @abstractmethod
    def _run_spider(self, since_time: datetime) -> List[RawArticle]:
        """
        子类必须实现的具体爬虫逻辑（如 BeautifulSoup 解析、翻页）
        """
        pass
    
    # def _run_spider_keyword(self, keyword_info: dict, since_time: datetime) -> List[RawArticle]:
    #     """
    #     子类必须实现的具体爬虫逻辑（如 BeautifulSoup 解析、翻页）
    #     """
    #     pass

    def fetch_all(self) -> List[RawArticle]:
        """
        逻辑：按照模型内关键词的最低水位线全量爬取
        """
        # 1. 获取该模型所有关键词及其最小水位线
        keywords_info = self.db.get_keywords_by_model(self.model_id)
        if not keywords_info: return []
        
        min_watermark = min(k['incremental_spider_time'] for k in keywords_info)
        
        # 2. 聚合关键词水位线进行爬取 (或循环爬取)
        all_results = self._run_spider(min_watermark)
       
        return self._deduplicate_raw(all_results)

    # def fetch_keyword(self, keyword_id: int) -> List[RawArticle]:
    #     """
    #     逻辑：按照特定关键词 ID 爬取
    #     """
    #     k_info = self.db.get_keyword_info(keyword_id)
    #     return self._run_spider_keyword(k_info, k_info['incremental_spider_time'])

    def _deduplicate_raw(self, articles: List[RawArticle]) -> List[RawArticle]:
        # 抓取层的初步 URL 去重，减轻 Processor 压力
        seen = set()
        return [a for a in articles if not (a.url in seen or seen.add(a.url))]