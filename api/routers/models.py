from __future__ import annotations

import importlib
import json
import shutil
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import text

from ..deps import _db, _lock, _running_locks, PROJECT_ROOT, DEFAULT_INCREMENTAL_TIME
from ..responses import ok, fail
from ..pipeline import _run_pipeline, _register_cron, _update_state
from ..fetcher_utils import (
    _normalize_fetcher_name,
    _stage_fetcher,
    _validate_fetcher,
    _promote_fetcher,
)
from utils.logger import get_logger

router = APIRouter()
logger = get_logger("SpiderAPI")


def _upsert_keywords(conn, model_id: int, kw_list: list[dict]):
    """在已有事务连接上批量 upsert 关键词（软删除 + 插入/更新）。"""
    incoming_ids = {int(kw["keywordId"]) for kw in kw_list if kw.get("keywordId")}
    if incoming_ids:
        placeholders = ",".join(str(i) for i in incoming_ids)
        conn.execute(
            text(
                f"UPDATE keyword SET deleted=1 WHERE model_id=:model_id "
                f"AND keyword_id NOT IN ({placeholders}) AND deleted=0"
            ),
            {"model_id": model_id},
        )
    else:
        conn.execute(
            text("UPDATE keyword SET deleted=1 WHERE model_id=:model_id AND deleted=0"),
            {"model_id": model_id},
        )

    for kw in kw_list:
        kid      = kw.get("keywordId")
        name     = kw.get("keywordName", "").strip()
        use_flag = kw.get("useFlag", 1)
        incr     = kw.get("incrementalSpiderTime") or DEFAULT_INCREMENTAL_TIME
        if not name:
            continue
        if kid:
            conn.execute(
                text(
                    "UPDATE keyword SET keyword_name=:name, use_flag=:use_flag, "
                    "incremental_spider_time=:incr, deleted=0 "
                    "WHERE keyword_id=:kid AND model_id=:model_id"
                ),
                {"name": name, "use_flag": use_flag, "incr": incr,
                 "kid": int(kid), "model_id": model_id},
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO keyword (model_id, keyword_name, incremental_spider_time, use_flag, deleted) "
                    "VALUES (:model_id, :name, :incr, :use_flag, 0)"
                ),
                {"model_id": model_id, "name": name, "incr": incr, "use_flag": use_flag},
            )


@router.get("/api/fetcher/list")
def list_fetchers() -> dict:
    fetchers_dir = PROJECT_ROOT / "fetchers"
    if not fetchers_dir.exists():
        logger.warning("fetchers directory does not exist: %s", fetchers_dir)
        return ok([])
    if not fetchers_dir.is_dir():
        logger.error("fetchers path is not a directory: %s", fetchers_dir)
        return fail("fetchers directory is invalid")

    names = []
    for d in sorted(fetchers_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("__"):
            continue
        if (d / f"{d.name}_fetcher.py").exists():
            names.append(d.name)
    return ok(names)


@router.get("/api/model/list")
def get_model_list(
    pageNum:  int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
):
    offset = (pageNum - 1) * pageSize
    total_rows = _db.query("SELECT COUNT(*) AS cnt FROM reptile_model WHERE deleted=0")
    total = total_rows[0]["cnt"] if total_rows else 0

    rows = _db.query(
        "SELECT m_reptile_model_id, m_reptile_model_name, "
        "m_reptile_model_introduce, m_reptile_model_web, "
        "m_reptile_model_state, m_reptile_model_time, "
        "m_reptile_model_script_address "
        "FROM reptile_model WHERE deleted=0 "
        "ORDER BY m_reptile_model_id DESC "
        "LIMIT :limit OFFSET :offset",
        {"limit": pageSize, "offset": offset},
    )
    records = [
        {
            "mReptileModelId":           r["m_reptile_model_id"],
            "mReptileModelName":         r["m_reptile_model_name"],
            "mReptileModelIntroduce":    r["m_reptile_model_introduce"],
            "mReptileModelWeb":          r["m_reptile_model_web"],
            "mReptileModelState":        r["m_reptile_model_state"],
            "mReptileModelTime":         str(r["m_reptile_model_time"]) if r["m_reptile_model_time"] else "",
            "mReptileModelScriptAddress": r["m_reptile_model_script_address"] or "",
        }
        for r in rows
    ]
    return ok({"records": records, "total": total})


@router.get("/api/model/{model_id}")
def get_model_detail(model_id: int):
    rows = _db.query(
        "SELECT m_reptile_model_id, m_reptile_model_name, m_reptile_model_introduce, "
        "m_reptile_model_web, m_reptile_model_state, m_reptile_model_time, "
        "m_reptile_model_script_address, cron_expression "
        "FROM reptile_model WHERE m_reptile_model_id=:id AND deleted=0",
        {"id": model_id},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="模型不存在")
    row = rows[0]

    kw_rows = _db.query(
        "SELECT keyword_id, keyword_name, use_flag, incremental_spider_time "
        "FROM keyword WHERE model_id=:model_id AND deleted=0 ORDER BY keyword_id ASC",
        {"model_id": model_id},
    )
    return ok({
        "mReptileModelId":            row["m_reptile_model_id"],
        "mReptileModelName":          row["m_reptile_model_name"],
        "mReptileModelIntroduce":     row["m_reptile_model_introduce"],
        "mReptileModelWeb":           row["m_reptile_model_web"],
        "mReptileModelState":         row["m_reptile_model_state"],
        "mReptileModelTime":          str(row["m_reptile_model_time"]) if row["m_reptile_model_time"] else "",
        "mReptileModelScriptAddress": row["m_reptile_model_script_address"] or "",
        "cronExpression":             row["cron_expression"] or "",
        "keywords": [
            {
                "keywordId":             k["keyword_id"],
                "keywordName":           k["keyword_name"],
                "useFlag":               k["use_flag"],
                "incrementalSpiderTime": str(k["incremental_spider_time"]) if k["incremental_spider_time"] else "",
            }
            for k in kw_rows
        ],
    })


@router.post("/api/model/save")
async def save_model(
    mReptileModelId:        Optional[str]        = Form(None),
    mReptileModelName:      str                  = Form(...),
    mReptileModelIntroduce: str                  = Form(""),
    mReptileModelWeb:       str                  = Form(...),
    fetcherName:            str                  = Form(""),
    cronExpression:         str                  = Form(""),
    keywords:               str                  = Form("[]"),
    scriptFile:             Optional[UploadFile] = File(None),
):
    model_id   = int(mReptileModelId) if mReptileModelId else None
    kw_list    = json.loads(keywords) if keywords else []
    staged_dir = None

    fetcherName = _normalize_fetcher_name(fetcherName)
    if scriptFile and scriptFile.filename and not fetcherName:
        fetcherName = _normalize_fetcher_name(scriptFile.filename)

    if scriptFile and scriptFile.filename:
        if not fetcherName:
            return fail("上传脚本时必须填写爬虫模块名", code=400)
        try:
            staged_dir = _stage_fetcher(scriptFile, fetcherName)
            _validate_fetcher(staged_dir, fetcherName)
        except Exception as e:
            if staged_dir and staged_dir.exists():
                shutil.rmtree(staged_dir, ignore_errors=True)
            return fail(f"采集器校验失败：{e}", code=400)

    try:
        if staged_dir is not None:
            _promote_fetcher(staged_dir, fetcherName)
            importlib.invalidate_caches()
            staged_dir = None

        with _db.transaction() as conn:
            is_edit = False
            if model_id:
                row = conn.execute(
                    text("SELECT m_reptile_model_id FROM reptile_model "
                         "WHERE m_reptile_model_id=:id AND deleted=0"),
                    {"id": model_id},
                ).fetchone()
                is_edit = row is not None

            if is_edit:
                set_parts = (
                    "m_reptile_model_name=:name, m_reptile_model_introduce=:intro, "
                    "m_reptile_model_web=:web, cron_expression=:cron"
                )
                params: dict = {
                    "name":  mReptileModelName,
                    "intro": mReptileModelIntroduce,
                    "web":   mReptileModelWeb,
                    "cron":  cronExpression or None,
                    "id":    model_id,
                }
                if fetcherName:
                    set_parts += ", m_reptile_model_script_address=:fetcher"
                    params["fetcher"] = fetcherName
                conn.execute(
                    text(f"UPDATE reptile_model SET {set_parts} "
                         f"WHERE m_reptile_model_id=:id AND deleted=0"),
                    params,
                )
                assert model_id is not None
                _upsert_keywords(conn, model_id, kw_list)

            else:
                result = conn.execute(
                    text(
                        "INSERT INTO reptile_model "
                        "(m_reptile_model_name, m_reptile_model_introduce, m_reptile_model_web, "
                        "m_reptile_model_state, m_reptile_model_script_address, cron_expression, "
                        "m_reptile_model_time, deleted) "
                        "VALUES (:name, :intro, :web, 'stopped', :fetcher, :cron, NOW(), 0)"
                    ),
                    {
                        "name":    mReptileModelName,
                        "intro":   mReptileModelIntroduce,
                        "web":     mReptileModelWeb,
                        "fetcher": fetcherName or None,
                        "cron":    cronExpression or None,
                    },
                )
                model_id = result.lastrowid
                for kw in kw_list:
                    name     = kw.get("keywordName", "").strip()
                    use_flag = kw.get("useFlag", 1)
                    incr     = kw.get("incrementalSpiderTime") or DEFAULT_INCREMENTAL_TIME
                    if not name:
                        continue
                    conn.execute(
                        text(
                            "INSERT INTO keyword (model_id, keyword_name, incremental_spider_time, use_flag, deleted) "
                            "VALUES (:model_id, :name, :incr, :use_flag, 0)"
                        ),
                        {"model_id": model_id, "name": name, "incr": incr, "use_flag": use_flag},
                    )

    except Exception as e:
        logger.error(f"保存模型失败：{e}", exc_info=True)
        return fail(f"保存失败：{e}")
    finally:
        if staged_dir and staged_dir.exists():
            shutil.rmtree(staged_dir, ignore_errors=True)

    if cronExpression and model_id is not None:
        _register_cron(model_id, cronExpression)

    return ok({"mReptileModelId": model_id}, "保存成功")


@router.delete("/api/model/{model_id}")
def delete_model(model_id: int):
    _db.execute(
        "UPDATE reptile_model SET deleted=1 WHERE m_reptile_model_id=:id",
        {"id": model_id},
    )
    return ok(message="删除成功")


@router.post("/api/model/{model_id}/start")
def start_model(model_id: int):
    with _lock:
        if _running_locks.get(model_id):
            return fail(f"model_id={model_id} 已在运行中", code=409)
        _running_locks[model_id] = True

    threading.Thread(target=_run_pipeline, args=(model_id, None), daemon=True).start()
    return ok(message="启动成功")


@router.post("/api/model/{model_id}/stop")
def stop_model(model_id: int):
    _update_state(model_id, "stopped")
    with _lock:
        _running_locks[model_id] = False
    return ok(message="停止成功")
