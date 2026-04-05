# processor/extractor.py
from __future__ import annotations

import time
from datetime import datetime
from typing import List, Optional

from pydantic import ValidationError

from ai.llm_client import OllamaClient
from ai.prompts import build_extract_system, build_extract_user
from ai.dimension_loader import load_dimension_tree
from models.schemas import CleanedItem, EnrichedItem, LLMExtractResult
from utils.logger import get_logger
from utils.geo_encoder import geocode

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
    ):
        self.client   = client or OllamaClient()
        self.db_conn  = db_conn
        self.logger   = get_logger(self.__class__.__name__)
        self._tree: dict = {}

    # ── 公开接口 ─────────────────────────────────────────────────────────

    def run(self, items: List[CleanedItem]) -> List[EnrichedItem]:
        self._tree = load_dimension_tree(self.db_conn)
        system_prompt = build_extract_system(self._tree)

        # 构建合法 dim3 id 集合，用于校验 LLM 输出
        self._valid_dim3_ids: set[int] = self._collect_dim3_ids(self._tree)
        self.logger.info(f"合法三级维度 id：{sorted(self._valid_dim3_ids)}")

        results: List[EnrichedItem] = []
        total = len(items)
        for idx, item in enumerate(items, 1):
            self.logger.info(f"[{idx}/{total}] {item.title[:50]}")
            enriched = self._extract_one(item, system_prompt)
            if enriched:
                results.append(enriched)
            time.sleep(_CALL_INTERVAL)

        ok = len(results)
        self.logger.info(f"完成 | 输入={total} 成功={ok} 跳过={total - ok}")
        return results

    # ── 核心流程 ─────────────────────────────────────────────────────────

    def _extract_one(self, item: CleanedItem, system_prompt: str) -> Optional[EnrichedItem]:
        for attempt in range(1, 4):
            try:
                raw = self.client.extract_json(
                    system=system_prompt,
                    user=build_extract_user(item.title, item.content, item.raw_location),
                )
                llm = LLMExtractResult(**raw)

                if not llm.is_target_info:
                    self.logger.info("       ⚠ AI判定为非目标信息，跳过")
                    return None

                # 校验 dim3_id 合法性
                if llm.dim3_id is not None and llm.dim3_id not in self._valid_dim3_ids:
                    self.logger.warning(
                        f"       ⚠ dim3_id={llm.dim3_id} 不在维度树中，已清空"
                    )
                    llm.dim3_id = None
                    llm.dim3_name = None

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
        if llm.is_target_info:
            location = llm.device_location or item.raw_location
            lng, lat  = geocode(location) if location else (None, None)
        return EnrichedItem(
            device_name=llm.device_name or item.title,
            device_class_id=llm.dim1_id,
            device_style_id=llm.dim2_id,
            device_type_id=llm.dim3_id,
            device_use_year=llm.device_use_year,
            device_price=llm.device_price,
            device_using_unit=llm.device_using_unit,
            device_country_id=COUNTRY_NAME_MAP.get(llm.country_name) if llm.country_name else None,
            device_location=llm.device_location or item.raw_location,
            device_longitude=lng,   # ← 自动填充
            device_latitude=lat,    # ← 自动填充
            device_img=",".join(item.img_urls) if item.img_urls else None,
            device_video=",".join(item.video_urls) if item.video_urls else None,
            device_introduce=llm.device_introduce,
            device_keywords=llm.device_keywords,
            device_news_link=item.url,
            device_news_title=item.title,
            device_news_time=item.pub_time,
            device_insql_time=now,
            device_changesql_time=now,
            audit_flag=0,
            deleted=0,
        )

    # ── 工具方法 ─────────────────────────────────────────────────────────

    @staticmethod
    def _collect_dim3_ids(tree: dict) -> set[int]:
        """从维度树中收集所有合法的三级方向 id。"""
        ids: set[int] = set()
        for d1 in tree.values():
            for d2 in d1.get("children", {}).values():
                for d3 in d2.get("directions", []):
                    ids.add(d3["id"])
        return ids