"""
过滤器（Filter）—— 流水线第一道工序。

输入 : List[RawArticle]   fetcher 输出（列表页数据，content 为空）
输出 : List[FilteredItem] 命中文章 + 详情页正文 + matched_keyword_ids

两关顺序执行：
  关1 - 时间水位线
        pub_time < min(所有关键词水位线) → 丢弃
        pub_time 为 None → 放行（时间未知，交给关2判断）

  关2 - 详情页抓取 + AC 自动机
        先 GET 详情页拿到正文 content，
        再在 title + content 中做 AC 匹配，
        无命中 → 丢弃；命中 → 记录 matched_keyword_ids，输出 FilteredItem

不写数据库，不更新水位线（由 Exporter 负责）。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

from models.schemas import RawArticle, KeywordConfig
from models.schemas import FilteredItem
from utils.logger import get_logger
from processor.ac_engine import KeywordAC, SemanticMatcher

# 抓详情页的超时与重试
_FETCH_TIMEOUT = 10        # 秒
_RETRY_TIMES   = 2
_RETRY_DELAY   = 1.5       # 秒
_DEFAULT_UA    = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class ArticleFilter:
    """
    一个 model_id 对应一个实例，构造时查一次数据库，整批复用。
    """

    def __init__(self, model_id: int, db_manager, semantic_threshold: float = 0.65):
        self.model_id  = model_id
        self.db        = db_manager
        self.logger    = get_logger(self.__class__.__name__)

        raw_kws: List[Dict] = self.db.get_keywords_by_model(model_id)
        self._keywords: List[KeywordConfig] = [KeywordConfig(**kw) for kw in raw_kws]

        if not self._keywords:
            self.logger.warning(f"model_id={model_id} 无活跃关键词，所有文章将被丢弃")

        self._min_watermark: Optional[datetime] = self._calc_min_watermark()

        kw_map = {kw.keyword_id: kw.keyword_name for kw in self._keywords}

        # 关2-A：AC 精确/变体匹配（快）
        self._ac = KeywordAC.build(kw_map)

        # 关2-B：语义向量兜底（慢，仅 AC 未命中时触发）
        self._semantic = SemanticMatcher.build(kw_map, threshold=semantic_threshold)

        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _DEFAULT_UA})

        self.logger.info(
            f"model_id={model_id} 过滤器就绪 | "
            f"关键词={len(self._keywords)} | 水位线={self._min_watermark} | "
            f"语义阈值={semantic_threshold}"
        )

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def run(self, articles: List[RawArticle]) -> List[FilteredItem]:
        if not articles or not self._keywords:
            return []

        total     = len(articles)
        after_wm  = self._stage1_watermark(articles)
        after_ac  = self._stage2_fetch_and_match(after_wm)

        self.logger.info(
            f"model_id={self.model_id} | "
            f"输入={total} 水位线后={len(after_wm)} AC后={len(after_ac)}"
        )
        return after_ac

    # ------------------------------------------------------------------
    # 关1：时间水位线
    # ------------------------------------------------------------------

    def _calc_min_watermark(self) -> Optional[datetime]:
        times = [
            kw.incremental_spider_time
            for kw in self._keywords
            if kw.incremental_spider_time is not None
        ]
        return min(times) if times else None

    def _stage1_watermark(self, articles: List[RawArticle]) -> List[RawArticle]:
        if self._min_watermark is None:
            return articles                    # 未配置水位线，全部放行

        passed, dropped = [], 0
        for a in articles:
            if a.pub_time is None or a.pub_time >= self._min_watermark:
                passed.append(a)
            else:
                dropped += 1

        if dropped:
            self.logger.debug(f"关1 丢弃 {dropped} 篇（早于 {self._min_watermark}）")
        return passed

    # ------------------------------------------------------------------
    # 关2：抓详情页 → AC → （未命中）→ 语义
    # ------------------------------------------------------------------

    def _stage2_fetch_and_match(self, articles: List[RawArticle]) -> List[FilteredItem]:
        result: List[FilteredItem] = []

        for article in articles:
            content     = self._fetch_content(article.url)
            search_text = self._build_search_text(article.title, content)

            # ── 第一道：AC 精确匹配 ──────────────────────────────────
            matched_ids = self._ac.search(search_text)

            if matched_ids:
                self.logger.debug(f"AC命中 {matched_ids}: {article.url[:80]}")

            else:
                # ── 第二道：语义向量兜底 ─────────────────────────────
                matched_ids = self._semantic.search(search_text)

                if matched_ids:
                    self.logger.debug(f"语义命中 {matched_ids}: {article.url[:80]}")
                else:
                    self.logger.debug(f"AC+语义均未命中，丢弃: {article.url[:80]}")

            if matched_ids:
                result.append(FilteredItem(
                    article=article,
                    content=content,
                    matched_keyword_ids=matched_ids,
                ))

        return result

    def _fetch_content(self, url: str) -> str:
        """
        GET 详情页，提取正文纯文本。
        失败时返回空字符串（不抛异常，让 AC 匹配空串后自然丢弃）。
        """
        for attempt in range(1, _RETRY_TIMES + 1):
            try:
                resp = self._session.get(url, timeout=_FETCH_TIMEOUT)
                resp.raise_for_status()
                # 优先用 apparent_encoding 处理 GBK 页面
                resp.encoding = resp.apparent_encoding
                return self._extract_text(resp.text)
            except requests.RequestException as e:
                self.logger.warning(f"详情页抓取失败({attempt}/{_RETRY_TIMES}): {url} | {e}")
                if attempt < _RETRY_TIMES:
                    time.sleep(_RETRY_DELAY)
        return ""

    @staticmethod
    def _extract_text(html: str) -> str:
        """BeautifulSoup 提取正文纯文本，去除脚本/样式噪声。"""
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)

    @staticmethod
    def _build_search_text(title: Optional[str], content: str) -> str:
        """拼接检索文本，换行分隔防止跨字段幻影匹配。"""
        parts = [p for p in (title, content) if p]
        return "\n".join(parts)