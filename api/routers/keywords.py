from __future__ import annotations

from fastapi import APIRouter

from ..deps import _db, DEFAULT_INCREMENTAL_TIME
from ..responses import ok
from ..schemas import KeywordCreateBody

router = APIRouter()


@router.get("/api/model/{model_id}/keywords")
def get_keywords(model_id: int):
    rows = _db.query(
        "SELECT keyword_id, keyword_name, use_flag, incremental_spider_time "
        "FROM keyword WHERE model_id=:model_id AND deleted=0 "
        "ORDER BY keyword_id ASC",
        {"model_id": model_id},
    )
    return ok([
        {
            "keywordId":             r["keyword_id"],
            "keywordName":           r["keyword_name"],
            "useFlag":               r["use_flag"],
            "incrementalSpiderTime": str(r["incremental_spider_time"]) if r["incremental_spider_time"] else "",
        }
        for r in rows
    ])


@router.post("/api/model/keyword")
def add_keyword(body: KeywordCreateBody):
    keyword_id = _db.insert(
        "INSERT INTO keyword (model_id, keyword_name, incremental_spider_time, use_flag, deleted) "
        "VALUES (:model_id, :keyword_name, :incr_time, :use_flag, 0)",
        {
            "model_id":     body.modelId,
            "keyword_name": body.keywordName,
            "incr_time":    DEFAULT_INCREMENTAL_TIME,
            "use_flag":     body.useFlag,
        },
    )
    return ok({"keywordId": keyword_id}, "添加成功")


@router.delete("/api/model/keyword/{keyword_id}")
def delete_keyword(keyword_id: int):
    _db.execute(
        "UPDATE keyword SET deleted=1 WHERE keyword_id=:keyword_id",
        {"keyword_id": keyword_id},
    )
    return ok(message="删除成功")
