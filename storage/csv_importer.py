# storage/csv_importer.py
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from utils.logger import get_logger

if TYPE_CHECKING:
    from storage.db_manager import DatabaseManager

logger = get_logger("CsvImporter")

DEVICE_FIELDS = [
    "device_name", "device_class_id", "device_style_id", "device_type_id",
    "device_use_year", "device_price", "device_using_unit",
    "device_country_id", "device_location", "device_longitude", "device_latitude",
    "device_img", "device_video", "device_introduce", "device_keywords",
    "device_news_link", "device_news_title", "device_news_time",
    "audit_flag",
]

_INT_FIELDS = {
    "device_class_id", "device_style_id", "device_type_id",
    "device_use_year", "device_country_id", "audit_flag",
}


class CsvImporter:
    """
    读取 CSV 文件 → 写入 device 表 → 写入 csv_enter_logs 表

    调用方式：
        importer = CsvImporter(db)
        result = importer.run(
            csv_path="data/output/model_1_xxx.csv",
            model_log_id=1,
            user_id=1,
        )
    """

    def __init__(self, db: "DatabaseManager"):
        self.db = db

    def run(
        self,
        csv_path: str | Path,
        model_log_id: int,
        user_id: int = 0,
        img_dir: Optional[str | Path] = None,
        video_dir: Optional[str | Path] = None,
    ) -> dict:
        csv_path = Path(csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV 文件不存在：{csv_path}")

        rows    = self._read_csv(csv_path)
        total   = len(rows)
        success = 0
        errors  = []

        logger.info(f"开始导入：{csv_path.name}，共 {total} 行")

        for i, row in enumerate(rows, 1):
            try:
                row = self._resolve_attachments(row, img_dir, video_dir)
                self._insert_device(row)
                success += 1
            except Exception as e:
                msg = f"第{i}行导入失败：{e}"
                errors.append(msg)
                logger.warning(msg)

        failed   = total - success
        log_text = self._build_log_text(csv_path.name, total, success, failed, errors)
        log_id   = self._write_enter_log(
            model_log_id=model_log_id,
            log_text=log_text,
            total=total,
            success=success,
            user_id=user_id,
        )

        logger.info(f"导入完成：总={total} 成功={success} 失败={failed} log_id={log_id}")
        return {
            "total":   total,
            "success": success,
            "failed":  failed,
            "log_id":  log_id,
            "errors":  errors,
        }

    # ── 读 CSV ───────────────────────────────────────────────────────────

    @staticmethod
    def _read_csv(csv_path: Path) -> list[dict]:
        rows = []
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cleaned = {k: (v if v != "" else None) for k, v in row.items()}
                rows.append(cleaned)
        return rows

    # ── 附件处理 ─────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_attachments(
        row: dict,
        img_dir: Optional[str | Path],
        video_dir: Optional[str | Path],
    ) -> dict:
        if img_dir and row.get("device_img"):
            img_path = Path(img_dir) / row["device_img"]
            if img_path.exists():
                row["device_img"] = str(img_path)

        if video_dir and row.get("device_video"):
            video_path = Path(video_dir) / row["device_video"]
            if video_path.exists():
                row["device_video"] = str(video_path)

        return row

    # ── 写 device 表 ─────────────────────────────────────────────────────

    def _insert_device(self, row: dict):
        now = datetime.now()

        def _cast(field: str, v):
            if v is None:
                return None
            return int(v) if field in _INT_FIELDS else str(v).strip()

        params = {f: _cast(f, row.get(f)) for f in DEVICE_FIELDS}
        params["device_insql_time"]   = now
        params["device_changesql_time"] = now
        params["deleted"] = 0

        self.db.execute(
            """
            INSERT INTO device (
                device_name, device_class_id, device_style_id, device_type_id,
                device_use_year, device_price, device_using_unit,
                device_country_id, device_location, device_longitude, device_latitude,
                device_img, device_video, device_introduce, device_keywords,
                device_news_link, device_news_title, device_news_time,
                device_insql_time, device_changesql_time,
                audit_flag, deleted
            ) VALUES (
                :device_name, :device_class_id, :device_style_id, :device_type_id,
                :device_use_year, :device_price, :device_using_unit,
                :device_country_id, :device_location, :device_longitude, :device_latitude,
                :device_img, :device_video, :device_introduce, :device_keywords,
                :device_news_link, :device_news_title, :device_news_time,
                :device_insql_time, :device_changesql_time,
                :audit_flag, :deleted
            )
            """,
            params,
        )

    # ── 写 csv_enter_logs 表 ─────────────────────────────────────────────

    def _write_enter_log(
        self,
        model_log_id: int,
        log_text: str,
        total: int,
        success: int,
        user_id: int,
    ) -> int:
        return self.db.insert(
            """
            INSERT INTO csv_enter_logs (
                model_log_id, csv_enter_logs, csv_enter_number,
                csv_enter_success_number, csv_enter_logs_time,
                csv_enter_user_id, deleted
            ) VALUES (
                :model_log_id, :log_text, :total,
                :success, :now,
                :user_id, 0
            )
            """,
            {
                "model_log_id": model_log_id,
                "log_text":     log_text,
                "total":        total,
                "success":      success,
                "now":          datetime.now(),
                "user_id":      user_id,
            },
        )

    # ── 日志文本拼装 ─────────────────────────────────────────────────────

    @staticmethod
    def _build_log_text(
        filename: str,
        total: int,
        success: int,
        failed: int,
        errors: list[str],
    ) -> str:
        lines = [
            f"文件：{filename}",
            f"总计：{total} 条",
            f"成功：{success} 条",
            f"失败：{failed} 条",
        ]
        if errors:
            lines.append("── 错误详情 ──")
            lines.extend(errors[:50])
            if len(errors) > 50:
                lines.append(f"... 还有 {len(errors)-50} 条错误未显示")
        return "\n".join(lines)
