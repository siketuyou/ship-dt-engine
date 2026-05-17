from datetime import datetime
from typing import List

from fetchers.base_fetcher import BaseFetcher
from models.schemas import RawArticle


class Test1Fetcher(BaseFetcher):
    def _run_spider(self, since_time: datetime) -> List[RawArticle]:
        return []