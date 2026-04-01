# ai/dimension_loader.py
from __future__ import annotations

import time
from utils.logger import get_logger

logger = get_logger("DimensionLoader")

_cache: dict = {}
_cache_ts: float = 0.0
_CACHE_TTL: float = 600.0  # 10分钟


def load_dimension_tree(db_conn=None) -> dict:
    """
    返回结构：
    {
      "硬件基础设施": {
        "id": 1,
        "children": {
          "智能设备": {
            "id": 11,
            "directions": [
              {"id": 101, "name": "机器人焊接"},
              {"id": 102, "name": "AGV自动导引车"},
            ]
          }
        }
      }
    }
    """
    global _cache, _cache_ts

    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    if db_conn is None:
        logger.warning("db_conn 为 None，使用静态维度树兜底")
        return _static_fallback()

    try:
        tree = _query_tree(db_conn)
        _cache = tree
        _cache_ts = now
        logger.info(f"维度树已刷新：{len(tree)} 个一级维度")
        return tree
    except Exception as e:
        logger.error(f"维度树加载失败，降级静态树：{e}")
        return _static_fallback()


def invalidate_cache():
    """手动失效缓存，用于写入新三级方向后立即刷新。"""
    global _cache, _cache_ts
    _cache = {}
    _cache_ts = 0.0


def _query_tree(db_conn) -> dict:
    cursor = db_conn.cursor()
    tree: dict = {}
    dim1_index: dict[int, str] = {}   # class_id → class_name，供关联用
    dim2_index: dict[int, str] = {}   # style_id  → style_name

    # ── 一级维度 ──────────────────────────────────────────────────────────
    cursor.execute(
        "SELECT device_class_id, device_class_name "
        "FROM device_class WHERE deleted = 0 OR deleted IS NULL "
        "ORDER BY device_class_id"
    )
    for row in cursor.fetchall():
        cid, cname = row[0], row[1]
        dim1_index[cid] = cname
        tree[cname] = {"id": cid, "children": {}}

    # ── 二级维度 ──────────────────────────────────────────────────────────
    cursor.execute(
        "SELECT device_style_id, device_style_name, device_style_class_id "
        "FROM device_style WHERE deleted = 0 OR deleted IS NULL "
        "ORDER BY device_style_id"
    )
    for row in cursor.fetchall():
        sid, sname, parent_cid = row[0], row[1], row[2]
        dim2_index[sid] = sname
        parent_name = dim1_index.get(parent_cid)
        if parent_name and parent_name in tree:
            tree[parent_name]["children"][sname] = {"id": sid, "directions": []}

    # ── 三级方向 ──────────────────────────────────────────────────────────
    cursor.execute(
        "SELECT device_type_id, device_type_name, device_type_style_id "
        "FROM device_type WHERE deleted = 0 OR deleted IS NULL "
        "ORDER BY device_type_id"
    )
    for row in cursor.fetchall():
        tid, tname, parent_sid = row[0], row[1], row[2]
        parent_sname = dim2_index.get(parent_sid)
        if not parent_sname:
            continue
        # 找到该二级维度挂在哪个一级下
        for d1_data in tree.values():
            if parent_sname in d1_data["children"]:
                d1_data["children"][parent_sname]["directions"].append(
                    {"id": tid, "name": tname}
                )
                break

    cursor.close()
    return tree


def _static_fallback() -> dict:
    """无数据库连接时的静态兜底，结构与 _query_tree 返回一致。"""
    return {
        "硬件基础设施": {
            "id": 1,
            "children": {
                "智能设备": {
                    "id": 11,
                    "directions": [
                        {"id": 101, "name": "机器人焊接"},
                        {"id": 102, "name": "机器人喷涂"},
                        {"id": 103, "name": "机器人装配"},
                        {"id": 104, "name": "AGV自动导引车"},
                    ]
                },
                "船厂硬件优化": {
                    "id": 12,
                    "directions": [
                        {"id": 105, "name": "柔性自动化生产线"},
                        {"id": 106, "name": "高精度数控机床"},
                        {"id": 107, "name": "3D打印增材制造"},
                    ]
                },
            }
        },
        "软件基础设施": {
            "id": 2,
            "children": {
                "管理系统": {
                    "id": 21,
                    "directions": [
                        {"id": 201, "name": "MES制造执行系统"},
                        {"id": 202, "name": "ERP企业资源计划"},
                    ]
                },
                "数据管理": {
                    "id": 22,
                    "directions": [
                        {"id": 203, "name": "PDM产品数据管理"},
                        {"id": 204, "name": "PLM产品全生命周期管理"},
                    ]
                },
            }
        },
        "网络基础设施": {
            "id": 3,
            "children": {
                "工业网络": {
                    "id": 31,
                    "directions": [
                        {"id": 301, "name": "5G专网覆盖"},
                        {"id": 302, "name": "时间敏感网络TSN"},
                    ]
                },
                "数据平台": {
                    "id": 32,
                    "directions": [
                        {"id": 303, "name": "工业互联网平台"},
                        {"id": 304, "name": "智慧港口数据接口"},
                    ]
                },
            }
        },
        "绿色与安全基础设施": {
            "id": 4,
            "children": {
                "绿色动力": {
                    "id": 41,
                    "directions": [
                        {"id": 401, "name": "LNG液化天然气设施"},
                        {"id": 402, "name": "氢气储运加注"},
                    ]
                },
                "安全防护": {
                    "id": 42,
                    "directions": [
                        {"id": 403, "name": "工业防火墙"},
                        {"id": 404, "name": "数据加密网络"},
                    ]
                },
            }
        },
    }