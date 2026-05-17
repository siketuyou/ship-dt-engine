from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from storage.db_manager import DatabaseManager

DEFAULT_INCREMENTAL_TIME = "2000-01-01 00:00:00"

OUTPUT_DIR = settings.OUTPUT_DIR
UPLOAD_DIR = Path(settings.UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

_db = DatabaseManager(settings.db_url)
_scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
_running_locks: dict[int, bool] = {}
_lock = threading.Lock()
