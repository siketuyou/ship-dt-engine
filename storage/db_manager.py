import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

class DatabaseManager:
    """
    基础数据库访问类 (DAO)
    职责：管理数据库连接池，执行原生 SQL。
    """
    def __init__(self, db_url: str):
        # 初始化 SQLAlchemy Engine (自带连接池)
        # db_url 格式: mysql+pymysql://user:pass@host:port/dbname
        self.engine: Engine = create_engine(
            db_url, 
            pool_size=10, 
            max_overflow=20,
            pool_recycle=3600
        )
        self.logger = logging.getLogger(__name__)

    # --- 基础通用接口 ---

    def query(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """执行 SELECT 查询，返回字典列表"""
        with self.engine.connect() as conn:
            result = conn.execute(text(sql), params)
            # 将结果集转为 List[Dict] 方便 Pydantic 转换
            return [dict(row._mapping) for row in result]

    def execute(self, sql: str, params: Optional[Dict[str, Any] | tuple] = ()) -> int:
        """执行 INSERT/UPDATE/DELETE，返回影响行数"""
        with self.engine.begin() as conn: # 使用 begin 自动开启事务
            result = conn.execute(text(sql), params)
            return result.rowcount

    # --- 针对 StateStore (L3) 的特定优化接口 ---

    def update_keywords_watermark(self, keyword_ids: List[int], new_timestamp: Any) -> bool:
        """
        批量更新关键词水位线 (对应表 10)
        """
        if not keyword_ids: return False
        
        sql = """
            UPDATE m_keyword 
            SET incremental_spider_time = :ts, keyword_change_time = NOW() 
            WHERE keyword_id IN :ids AND deleted = 0
        """
        try:
            # SQLAlchemy 会自动处理 list 到 IN (...) 的映射
            self.execute(sql, {"ts": new_timestamp, "ids": tuple(keyword_ids)})
            return True
        except Exception as e:
            self.logger.error(f"Batch update watermark failed: {e}")
            return False

    # --- 针对 Exporter (L8) 的特定优化接口 ---

    def insert_news_item(self, data: Dict[str, Any]):
        """
        持久化新闻数据 (对应表 4)
        TODO: 映射字段：device_news_title, device_news_link, device_news_time 等
        """
        # 使用冒号占位符防 SQL 注入
        fields = ", ".join(data.keys())
        placeholders = ", ".join([f":{k}" for k in data.keys()])
        sql = f"INSERT INTO m_device_news ({fields}) VALUES ({placeholders})"
        
        return self.execute(sql, data)