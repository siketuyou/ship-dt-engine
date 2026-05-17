# utils/geo_encoder.py
from __future__ import annotations

import httpx
from typing import Optional, Tuple
from utils.logger import get_logger
from config.settings import settings

logger = get_logger("GeoEncoder")

# 高德 API 失败时的城市级坐标兜底表（覆盖主要造船/船配城市）
_CITY_FALLBACK: dict[str, Tuple[str, str]] = {
    "上海":   ("121.473701", "31.230416"),
    "大连":   ("121.618622", "38.914589"),
    "广州":   ("113.280637", "23.125178"),
    "武汉":   ("114.298572", "30.584355"),
    "北京":   ("116.407387", "39.904179"),
    "青岛":   ("120.382639", "36.067082"),
    "天津":   ("117.200983", "39.084158"),
    "南京":   ("118.767413", "32.041544"),
    "宁波":   ("121.549792", "29.868388"),
    "舟山":   ("122.207216", "29.985295"),
    "南通":   ("120.864608", "32.016212"),
    "扬州":   ("119.412966", "32.394209"),
    "镇江":   ("119.452753", "32.204402"),
    "无锡":   ("120.301663", "31.574729"),
    "苏州":   ("120.619585", "31.299379"),
    "杭州":   ("120.153576", "30.287459"),
    "福州":   ("119.306239", "26.075302"),
    "厦门":   ("118.089425", "24.479834"),
    "葫芦岛": ("120.837392", "40.710926"),
    "烟台":   ("121.391382", "37.539297"),
    "威海":   ("122.116394", "37.509691"),
    "重庆":   ("106.551557", "29.563009"),
    "深圳":   ("114.085947", "22.547"),
    "珠海":   ("113.576726", "22.270703"),
    "长兴岛": ("121.543171", "31.419237"),
}


def _city_fallback(address: str) -> Tuple[Optional[str], Optional[str]]:
    """按城市名关键词匹配静态坐标表，先精确后模糊。"""
    for city, coord in _CITY_FALLBACK.items():
        if city in address:
            return coord
    return None, None


def geocode(address: str) -> Tuple[Optional[str], Optional[str]]:
    """
    输入地址字符串，返回 (longitude, latitude) 字符串元组。
    优先调用高德 API；API 失败或无结果时降级到城市级静态坐标。
    """
    if not address:
        return None, None
    try:
        resp = httpx.get(
            settings.AMAP_URL,
            params={"key": settings.AMAP_KEY, "address": address, "output": "JSON"},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "1" and data.get("geocodes"):
            location: str = data["geocodes"][0]["location"]  # "121.472644,31.231706"
            lng, lat = location.split(",")
            return lng, lat
        logger.debug(f"高德无结果，降级到城市兜底：{address}")
    except Exception as e:
        logger.warning(f"高德 API 失败，降级到城市兜底：{address} | {e}")

    return _city_fallback(address)