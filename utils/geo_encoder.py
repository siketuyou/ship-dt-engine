# utils/geo_encoder.py
from __future__ import annotations

import httpx
from typing import Optional, Tuple
from utils.logger import get_logger
from config.settings import AMAP_KEY,AMAP_URL
logger = get_logger("GeoEncoder")




def geocode(address: str) -> Tuple[Optional[str], Optional[str]]:
    """
    输入地址字符串，返回 (longitude, latitude) 字符串元组。
    失败时返回 (None, None)。
    """
    if not address:
        return None, None
    try:
        resp = httpx.get(
            AMAP_URL,
            params={"key": AMAP_KEY, "address": address, "output": "JSON"},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "1" and data.get("geocodes"):
            location: str = data["geocodes"][0]["location"]  # "121.472644,31.231706"
            lng, lat = location.split(",")
            return lng, lat
    except Exception as e:
        logger.warning(f"地理编码失败：{address} | {e}")
    return None, None