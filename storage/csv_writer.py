# storage/csv_writer.py

import csv
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from models.schemas import EnrichedItem
from utils.logger import get_logger

logger = get_logger("CsvWriter")

CSV_FIELDS = [
    "device_name", "device_class_id", "device_style_id", "device_type_id",
    "device_keywords", "device_use_year", "device_price", "device_using_unit",
    "device_location", "device_longitude", "device_latitude", "device_country_id",
    "device_introduce", "device_img", "device_video",
    "device_news_link", "device_news_title", "device_news_time",
    "audit_flag", "deleted",
]


class CsvWriter:

    def __init__(self, output_dir: str | Path = "data/output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        items: List[EnrichedItem],
        model_id: int,
        model_name: str,
        keywords: List[str],
        total_fetched: int,       # Fetcher 抓取总数
        total_filtered: int,      # Filter 后数量
        total_input: int,         # 进入 Extractor 的数量
        db_conn=None,
        user_id: int = 0,
    ) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"model_{model_id}_{ts}.csv"
        filepath = self.output_dir / filename
        success_count = len(items)

        try:
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)

                # ── 摘要块 ──────────────────────────────────────
                writer.writerow(["===== 运行摘要 ====="])
                writer.writerow(["生成时间",      datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
                writer.writerow(["爬虫模型ID",    model_id])
                writer.writerow(["爬虫模型名称",  model_name])
                writer.writerow(["使用关键词",    "、".join(keywords)])
                writer.writerow([])
                writer.writerow(["抓取总数",      total_fetched])
                writer.writerow(["过滤后数量",    total_filtered])
                writer.writerow(["送入LLM数量",   total_input])
                writer.writerow(["提取成功数量",  success_count])
                writer.writerow(["跳过数量",      total_input - success_count])
                writer.writerow(["成功率",        f"{success_count / total_input * 100:.1f}%" if total_input else "N/A"])
                writer.writerow([])
                writer.writerow(["===== 数据明细 ====="])
                writer.writerow([])

                # ── 数据明细 ────────────────────────────────────
                dict_writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                dict_writer.writeheader()
                for item in items:
                    row = {field: getattr(item, field, None) for field in CSV_FIELDS}
                    if row.get("device_news_time"):
                        row["device_news_time"] = str(row["device_news_time"])
                    dict_writer.writerow(row)

            logger.info(f"CSV 已写入：{filepath}（{success_count} 条）")

        except Exception as e:
            logger.error(f"CSV 写入失败：{e}")
            raise
        return filepath

    @staticmethod
    def _write_log(db_conn, model_log_id, log_text, total, success, user_id):
        try:
            cursor = db_conn.cursor()
            cursor.execute(
                """
                INSERT INTO csv_enter_logs
                    (model_log_id, csv_enter_logs, csv_enter_number,
                     csv_enter_success_number, csv_enter_logs_time,
                     csv_enter_user_id, deleted)
                VALUES (%s, %s, %s, %s, %s, %s, 0)
                """,
                (model_log_id, log_text, total, success, datetime.now(), user_id),
            )
            db_conn.commit()
            cursor.close()
            logger.info(f"csv_enter_logs 写入成功")
        except Exception as e:
            logger.error(f"csv_enter_logs 写入失败：{e}")
            db_conn.rollback()