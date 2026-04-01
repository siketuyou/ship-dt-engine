import logging
from typing import List, Optional
from datetime import datetime
from .db_manager import DatabaseManager
from ..models.schemas import CrawlModel

class StateStore:
    """
    状态存储层：负责模型配置、增量水位线的维护与同步。
    """
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.logger = logging.getLogger(__name__)

    def get_all_active_models(self) -> List[CrawlModel]:
        """
        从数据库加载任务配置，并聚合水位线逻辑
        """
        # 1. 获取所有活跃模型 (表 9)
        active_models_raw = self.db.query(
            "SELECT * FROM m_reptile_model WHERE m_reptile_model_state='正在运行' AND deleted=0"
        )
        
        result_tasks = []
        for m in active_models_raw:
            m_id = m['m_reptile_model_id']
            
            # 2. 获取该模型关联的所有有效关键词 (表 10)
            keywords_data = self.db.query(
                "SELECT keyword_id, keyword_name, incremental_spider_time "
                "FROM m_keyword WHERE model_id=%s AND use_flag=1 AND deleted=0",
                (m_id,)
            )
            
            if not keywords_data:
                self.logger.warning(f"模型 {m_id} ({m['m_reptile_model_name']}) 未配置有效关键词，跳过。")
                continue

            # 3. 逻辑核心：计算最小水位线及其对应的关键词 ID
            # 使用 min() 函数寻找最旧的时间戳，确保本次抓取不会遗漏任何关键词的更新
            # 如果时间戳为空，默认给定一个极小值（如 1970年）
            min_keyword_record = min(
                keywords_data, 
                key=lambda x: x['incremental_spider_time'] if x['incremental_spider_time'] else datetime(1970, 1, 1)
            )
            
            min_ts = min_keyword_record['incremental_spider_time'] or datetime(1970, 1, 1)
            min_id = min_keyword_record['keyword_id']

            # 封装成 L2 Schema 对象
            task = CrawlModel(
                model_id=m_id,
                model_name=m['m_reptile_model_name'],
                target_url=m['m_reptile_model_web'],
                keywords=[k['keyword_name'] for k in keywords_data],
                keyword_ids=[k['keyword_id'] for k in keywords_data],
                watermark=min_ts,
                watermark_id=min_id  # 记录当前“拖后腿”的关键词 ID
            )
            result_tasks.append(task)

        return result_tasks

    def sync_watermark(self, model: CrawlModel, new_ts: datetime):
        """
        同步回写水位线：将该模型下所有参与本次任务的关键词时间戳推至最新。
        这里采用批量更新模式，保证模型内的关键词水位线对齐。
        """
        if not model.keyword_ids:
            return

        # 逻辑：更新表 10 中该模型下的所有活跃关键词
        # 只有当新时间戳 > 旧时间戳时才回写，防止数据时间抖动导致水位线倒退
        success = self.db.update_keywords_watermark(
            keyword_ids=model.keyword_ids, 
            new_timestamp=new_ts
        )
        
        if success:
            self.logger.info(f"模型 {model.model_id} 的水位线已全量更新至 {new_ts}")
        else:
            self.logger.error(f"模型 {model.model_id} 水位线回写失败！")
    # ---  特定模型全局水位 (Min Watermark) ---
    def get_model_config(self, model_id: int) -> Optional[CrawlModel]:
        """
        获取特定模型的配置。核心逻辑：聚合该模型下所有关键词，计算全局最低水位线。
        """
        # 查询模型基础信息
        model_info = self.db.query(
            "SELECT * FROM m_reptile_model WHERE m_reptile_model_id=%s AND deleted=0", (model_id,)
        )
        if not model_info: return None
        m = model_info[0]

        # 查询该模型关联的关键词列表
        keywords_data = self.db.query(
            "SELECT keyword_id, keyword_name, incremental_spider_time "
            "FROM m_keyword WHERE model_id=%s AND use_flag=1 AND deleted=0", (model_id,)
        )

        if not keywords_data:
            return None

        # 计算全局最低水位线（拖后腿原则）
        # 如果某个关键词没抓过（None），则强制设为远古时间
        min_record = min(
            keywords_data, 
            key=lambda x: x['incremental_spider_time'] if x['incremental_spider_time'] else datetime(1970, 1, 1)
        )

        return CrawlModel(
            model_id=m['m_reptile_model_id'],
            model_name=m['m_reptile_model_name'],
            target_url=m['m_reptile_model_web'],
            keywords=[k['keyword_name'] for k in keywords_data],
            keyword_ids=[k['keyword_id'] for k in keywords_data],
            watermark=min_record['incremental_spider_time'] or datetime(1970, 1, 1),
            watermark_id=min_record['keyword_id']
        )

    # ---  特定关键词水位 (Precise Watermark) ---
    def get_keyword_watermark(self, keyword_id: int) -> Optional[datetime]:
        """
        精准查询某个关键词的上次抓取时间。
        用于更精细的调度，例如某个关键词单独失败重试时。
        """
        res = self.db.query(
            "SELECT incremental_spider_time FROM m_keyword WHERE keyword_id=%s AND deleted=0",
            (keyword_id,)
        )
        return res[0]['incremental_spider_time'] if res else None