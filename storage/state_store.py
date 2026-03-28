"""
增量爬取状态持久化。
以 source 为 key，记录每个采集器最后一次成功抓取的时间戳。
下次运行时只抓取比该时间戳更新的内容。
"""
import json
from datetime import datetime
from pathlib import Path
from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class StateStore:
    def __init__(self, path: Path = settings.STATE_FILE):
        self._path = path
        self._data: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"状态文件读取失败，重置: {e}")
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_last_fetch_time(self, source: str) -> datetime | None:
        raw = self._data.get(source)
        if raw:
            return datetime.fromisoformat(raw)
        return None

    def update_last_fetch_time(self, source: str, dt: datetime | None = None) -> None:
        dt = dt or datetime.utcnow()
        self._data[source] = dt.isoformat()
        self._save()
        logger.debug(f"[StateStore] {source} 时间戳更新为 {dt.isoformat()}")