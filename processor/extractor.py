# processor/extractor.py
from __future__ import annotations

import time
from datetime import datetime
from typing import List, Optional

from pydantic import ValidationError

from ai.llm_client import OllamaClient
from ai.prompts import build_extract_system, build_extract_user
from ai.dimension_loader import load_dimension_tree, invalidate_cache
from models.schemas import CleanedItem, EnrichedItem, LLMExtractResult
from utils.logger import get_logger

COUNTRY_NAME_MAP: dict[str, int] = {
    "中国": 1, "日本": 2, "韩国": 3, "美国": 4,
    "德国": 5, "挪威": 6, "英国": 7, "法国": 8,
    "荷兰": 9, "希腊": 10,
}

_CALL_INTERVAL = 0.5


class Extractor:

    def __init__(
        self,
        client: Optional[OllamaClient] = None,
        db_conn=None,
        auto_insert_new_type: bool = False,   # True: 自动将新三级方向写入 device_type 表
    ):
        self.client = client or OllamaClient()
        self.db_conn = db_conn
        self.auto_insert_new_type = auto_insert_new_type
        self.logger = get_logger(self.__class__.__name__)
        self._tree: dict = {}

    # ── 公开接口 ─────────────────────────────────────────────────────────

    def run(self, items: List[CleanedItem]) -> List[EnrichedItem]:
        self._tree = load_dimension_tree(self.db_conn)
        system_prompt = build_extract_system(self._tree)

        results: List[EnrichedItem] = []
        total = len(items)
        for idx, item in enumerate(items, 1):
            self.logger.info(f"[{idx}/{total}] {item.title[:50]}")
            enriched = self._extract_one(item, system_prompt)
            if enriched:
                results.append(enriched)
            time.sleep(_CALL_INTERVAL)

        ok = len(results)
        self.logger.info(f"完成 | 输入={total} 成功={ok} 跳过={total-ok}")
        return results

    # ── 核心流程 ─────────────────────────────────────────────────────────

    def _extract_one(self, item: CleanedItem, system_prompt: str) -> Optional[EnrichedItem]:
        for attempt in range(1, 4):
            try:
                raw = self.client.extract_json(system=system_prompt,
                                               user=build_extract_user(
                                                   item.title, item.content, item.raw_location))
                llm = LLMExtractResult(**raw)
                return self._assemble(item, llm)
            except (ValueError, ValidationError) as e:
                self.logger.warning(f"第{attempt}次解析失败：{e}")
            except Exception as e:
                self.logger.warning(f"第{attempt}次模型/网络错误：{e}")
            time.sleep(attempt * 2)

        self.logger.error(f"跳过（3次均失败）：{item.url}")
        return None

    def _assemble(self, item: CleanedItem, llm: LLMExtractResult) -> EnrichedItem:
        now = datetime.now()

        # 三级方向处理
        dim3_id = llm.dim3_id
        dim3_suggest_name = None
        dim3_suggest_style_id = None

        if llm.dim3_is_new and llm.dim3_name:
            dim3_suggest_name = llm.dim3_name
            dim3_suggest_style_id = llm.dim2_id
            if self.auto_insert_new_type and self.db_conn and llm.dim2_id:
                # 自动写入新三级方向，audit_flag=0（待审核）
                dim3_id = self._insert_new_type(llm.dim3_name, llm.dim2_id)

        return EnrichedItem(
            device_name=llm.device_name,
            device_class_id=llm.dim1_id,           # 一级维度 id
            device_style_id=llm.dim2_id,            # 二级维度 id
            device_type_id=dim3_id,                 # 三级方向 id（新方向且不自动写库时为 None）
            device_use_year=llm.device_use_year,
            device_price=llm.device_price,
            device_using_unit=llm.device_using_unit,
            device_country_id=COUNTRY_NAME_MAP.get(llm.country_name) if llm.country_name else None,
            device_location=llm.device_location or item.raw_location,
            device_longitude=None,                  # 留给 geo_encoder
            device_latitude=None,
            device_img=",".join(item.img_urls) if item.img_urls else None,
            device_video=",".join(item.video_urls) if item.video_urls else None,
            device_introduce=llm.device_introduce or None,
            device_news_link=item.url,
            device_news_title=item.title,
            device_news_time=item.pub_time,
            device_insql_time=now,
            device_changesql_time=now,
            audit_flag=0,
            deleted=0,
            dim3_suggest_name=dim3_suggest_name,
            dim3_suggest_style_id=dim3_suggest_style_id,
        )

    def _insert_new_type(self, type_name: str, style_id: int) -> Optional[int]:
        # 调用前已在 _assemble 中确认 self.db_conn 非 None，
        # 但 Pylance 仍报错，用 assert 做类型收窄
        assert self.db_conn is not None, "_insert_new_type 不应在 db_conn=None 时调用"

        now = datetime.now()
        try:
            cursor = self.db_conn.cursor()   # ✓ assert 后 Pylance 知道非 None
            cursor.execute(
                """
                INSERT INTO device_type
                    (device_type_name, device_type_style_id,
                     device_type_insql_time, device_type_changesql_time, deleted)
                VALUES (%s, %s, %s, %s, 0)
                """,
                (type_name, style_id, now, now),
            )
            self.db_conn.commit()            # ✓
            new_id: int = cursor.lastrowid
            cursor.close()
            invalidate_cache()
            self.logger.info(f"新三级方向入库：{type_name}（style_id={style_id}）→ id={new_id}")
            return new_id
        except Exception as e:
            self.logger.error(f"新三级方向写库失败：{e}")
            self.db_conn.rollback()          # ✓
            return None
