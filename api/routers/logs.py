from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse

from ..deps import _db, UPLOAD_DIR
from ..responses import ok, fail
from storage.csv_importer import CsvImporter
from utils.logger import get_logger

router = APIRouter()
logger = get_logger("SpiderAPI")


@router.get("/api/model/logs")
def get_run_logs(
    modelId:  int           = Query(...),
    state:    Optional[str] = Query(None),
    pageNum:  int           = Query(1, ge=1),
    pageSize: int           = Query(10, ge=1, le=100),
):
    where_parts = ["model_id=:model_id", "deleted=0"]
    params: dict = {"model_id": modelId}

    if state:
        where_parts.append("run_state=:state")
        params["state"] = state

    where = " AND ".join(where_parts)
    offset = (pageNum - 1) * pageSize

    total_rows = _db.query(f"SELECT COUNT(*) AS cnt FROM reptile_model_log WHERE {where}", params)
    total = total_rows[0]["cnt"] if total_rows else 0

    params["limit"]  = pageSize
    params["offset"] = offset
    rows = _db.query(
        f"SELECT log_id, run_time, run_state, result_desc, csv_address, entry_state, entry_time "
        f"FROM reptile_model_log WHERE {where} "
        f"ORDER BY run_time DESC LIMIT :limit OFFSET :offset",
        params,
    )

    return ok({
        "records": [
            {
                "logId":      r["log_id"],
                "runTime":    str(r["run_time"]) if r["run_time"] else "",
                "runState":   r["run_state"],
                "resultDesc": r["result_desc"],
                "csvAddress": r["csv_address"],
                "entryState": r["entry_state"],
                "entryTime":  str(r["entry_time"]) if r["entry_time"] else "",
            }
            for r in rows
        ],
        "total": total,
    })


@router.delete("/api/model/{model_id}/logs")
def clear_run_logs(model_id: int):
    _db.execute(
        "UPDATE reptile_model_log SET deleted=1 WHERE model_id=:model_id",
        {"model_id": model_id},
    )
    return ok(message="清空成功")


@router.post("/api/model/import-csv")
async def import_csv(
    file:   UploadFile = File(...),
    logId:  int        = Form(...),
    userId: int        = Form(0),
):
    save_path = UPLOAD_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        result = CsvImporter(_db).run(
            csv_path=save_path,
            model_log_id=logId,
            user_id=userId,
        )
    except Exception as e:
        logger.error(f"CSV 导入异常：{e}", exc_info=True)
        return fail(f"导入失败：{e}")

    return ok(result, "导入成功")


@router.get("/api/model/download-csv")
def download_csv(filePath: str = Query(...)):
    path = Path(filePath).resolve()
    allowed = {UPLOAD_DIR.resolve(), Path("data/output").resolve()}
    if not any(path.is_relative_to(d) for d in allowed):
        raise HTTPException(status_code=403, detail="不允许访问该路径")
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path=path, media_type="text/csv", filename=path.name)
