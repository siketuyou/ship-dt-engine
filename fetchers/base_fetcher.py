"""
所有采集器的抽象基类。
子类只需实现 fetch() 方法，返回 list[RawArticle]。
"""
from abc import ABC, abstractmethod
from datetime import datetime
from models.schemas import RawArticle
from storage.state_store import StateStore
from utils.http_client import RateLimitedClient
from utils.logger import get_logger


class BaseFetcher(ABC):
    """
    子类约定：
    - self.source_name  必须唯一，用于 StateStore key
    - fetch(since)      增量抓取，返回 since 之后的新文章
    - ping()            连通性测试，返回 True/False
    """

    def __init__(self, state_store: StateStore):
        self.state_store = state_store
        self.http = RateLimitedClient()
        self.logger = get_logger(self.__class__.__name__)
        self.source_name: str = "base"  # 子类覆盖

    @abstractmethod
    def fetch(self, since: datetime | None = None) -> list[RawArticle]:
        """
        增量抓取。
        since=None 时执行全量抓取（首次运行）。
        返回发布时间 > since 的文章列表。
        """
        ...

    def ping(self) -> bool:
        """连通性测试，默认 GET 首页"""
        try:
            self.http.get(self._base_url)
            return True
        except Exception as e:
            self.logger.warning(f"[{self.source_name}] ping失败: {e}")
            return False

    def run_incremental(self) -> list[RawArticle]:
        """
        由 Pipeline 调用。
        自动读取上次时间戳，抓取后更新时间戳。
        """
        since = self.state_store.get_last_fetch_time(self.source_name)
        self.logger.info(
            f"[{self.source_name}] 增量抓取，since={since or '全量'}"
        )
        articles = self.fetch(since=since)
        if articles:
            self.state_store.update_last_fetch_time(self.source_name)
        self.logger.info(f"[{self.source_name}] 本次抓取 {len(articles)} 条")
        return articles

    @property
    def _base_url(self) -> str:
        """子类覆盖，用于 ping()"""
        return ""