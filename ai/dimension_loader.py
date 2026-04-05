# ai/dimension_loader.py
from __future__ import annotations

import time
from utils.logger import get_logger

logger = get_logger("DimensionLoader")

_cache: dict = {}
_cache_ts: float = 0.0
_CACHE_TTL: float = 600.0


def load_dimension_tree(db_conn=None) -> dict:
    global _cache, _cache_ts

    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    if db_conn is None:
        logger.warning("db_conn 为 None，使用静态维度树兜底（不写缓存）")
        return _static_fallback()   # ← 不写 _cache，下次还会重试

    try:
        tree = _query_tree(db_conn)
        _cache = tree              # ← 只有真实查询成功才写缓存
        _cache_ts = now
        logger.info(f"维度树已刷新：{len(tree)} 个一级维度")
        return tree
    except Exception as e:
        logger.error(f"维度树加载失败，降级静态树：{e}")
        return _static_fallback()  # ← 失败也不写缓存


def invalidate_cache():
    global _cache, _cache_ts
    _cache = {}
    _cache_ts = 0.0


def _query_tree(db_conn) -> dict:
    # 逻辑不变，复用原有实现
    cursor = db_conn.cursor()
    tree: dict = {}
    dim1_index: dict[int, str] = {}
    dim2_index: dict[int, str] = {}

    cursor.execute(
        "SELECT device_class_id, device_class_name "
        "FROM device_class WHERE deleted = 0 OR deleted IS NULL "
        "ORDER BY device_class_id"
    )
    for row in cursor.fetchall():
        cid, cname = row[0], row[1]
        dim1_index[cid] = cname
        tree[cname] = {"id": cid, "children": {}}

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
        for d1_data in tree.values():
            if parent_sname in d1_data["children"]:
                d1_data["children"][parent_sname]["directions"].append(
                    {"id": tid, "name": tname}
                )
                break

    cursor.close()
    return tree
def _static_fallback() -> dict:
    return {
        "行业动态": {
            "id": 1,
            "children": {
                "政策与法规动态": {
                    "id": 11,
                    "directions": []
                },
                "技术创新与突破": {
                    "id": 12,
                    "directions": []
                },
                "市场与资本动向": {
                    "id": 13,
                    "directions": []
                },
                "标杆企业与生态合作": {
                    "id": 14,
                    "directions": []
                },
            }
        },
        "基础设施建设": {
            "id": 2,
            "children": {
                "硬件基础设施": {
                    "id": 21,
                    "directions": [
                        {"id": 211, "name": "智能设备"},
                        {"id": 212, "name": "船厂硬件优化"},
                    ]
                },
                "软件基础设施": {
                    "id": 22,
                    "directions": [
                        {"id": 221, "name": "管理系统"},
                        {"id": 222, "name": "数据管理"},
                    ]
                },
                "网络基础设施": {
                    "id": 23,
                    "directions": [
                        {"id": 231, "name": "工业网络"},
                        {"id": 232, "name": "数据平台"},
                    ]
                },
                "绿色与安全基础设施": {
                    "id": 24,
                    "directions": [
                        {"id": 241, "name": "绿色动力"},
                        {"id": 242, "name": "安全防护"},
                    ]
                },
            }
        },
        "数字化典型案例": {
            "id": 3,
            "children": {
                "设计与研发": {
                    "id": 31,
                    "directions": [
                        {"id": 311, "name": "智能生产"},
                        {"id": 312, "name": "流程管理"},
                    ]
                },
                "生产与制造": {
                    "id": 32,
                    "directions": [
                        {"id": 321, "name": "供应链协同"},
                        {"id": 322, "name": "远程运维"},
                    ]
                },
                "运营与服务": {
                    "id": 33,
                    "directions": [
                        {"id": 331, "name": "数据驱动"},
                    ]
                },
            }
        },
    }
