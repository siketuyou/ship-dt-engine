# utils/http_client.py
"""带限速、重试、UA的HTTP客户端封装"""
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=settings.MAX_RETRIES,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": settings.USER_AGENT})
    return session


class RateLimitedClient:
    """每次 get/post 前强制等待 REQUEST_DELAY 秒"""

    def __init__(self):
        self._session = build_session()
        self._last_request_time: float = 0.0

    def _wait(self):
        elapsed = time.monotonic() - self._last_request_time
        gap = settings.REQUEST_DELAY - elapsed
        if gap > 0:
            time.sleep(gap)
        self._last_request_time = time.monotonic()

    def get(self, url: str, **kwargs) -> requests.Response:
        self._wait()
        logger.debug(f"GET {url}")
        resp = self._session.get(url, timeout=settings.REQUEST_TIMEOUT, **kwargs)
        resp.raise_for_status()
        return resp