"""
去重引擎（DedupEngine）—— 流水线第三道工序。

输入 : List[CleanedItem]  清洗器输出
输出 : List[CleanedItem]  去重后的条目

两级去重顺序执行：
  级1 - URL 指纹精确去重
        sha256(url) 完全一致 → 保留第一条，丢弃后续
        
  级2 - 内容语义去重（TF-IDF + 余弦相似度）
        将 title + content 向量化，两两余弦相似度 >= 0.85 视为重复，
        保留 pub_time 较新的一条（时间相同则保留先出现的）
        
        实现细节：
        - 使用 sklearn TfidfVectorizer，analyzer="char_wb" 对中文友好
          （无需分词，字符 n-gram 即可捕捉语义相似性）
        - 相似度矩阵只计算上三角，避免重复比较
        - 条目数 <= 1 时跳过向量化，直接返回
"""
from __future__ import annotations

from typing import List, Optional
from datetime import datetime

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from models.schemas import CleanedItem
from utils.logger import get_logger

SIMILARITY_THRESHOLD = 0.85


class DedupEngine:

    def __init__(self, threshold: float = SIMILARITY_THRESHOLD):
        self.threshold = threshold
        self.logger = get_logger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def run(self, items: List[CleanedItem]) -> List[CleanedItem]:
        if not items:
            return []

        before = len(items)

        # 级1：URL 指纹精确去重
        after_url = self._dedup_by_url(items)

        # 级2：内容语义去重
        after_semantic = self._dedup_by_content(after_url)

        self.logger.info(
            f"去重完成 | 输入={before} "
            f"URL去重后={len(after_url)} "
            f"语义去重后={len(after_semantic)}"
        )
        return after_semantic

    # ------------------------------------------------------------------
    # 级1：URL 指纹精确去重
    # ------------------------------------------------------------------

    def _dedup_by_url(self, items: List[CleanedItem]) -> List[CleanedItem]:
        seen: set[str] = set()
        result: List[CleanedItem] = []
        for item in items:
            fp = item.url_fingerprint
            if fp in seen:
                self.logger.debug(f"URL重复，丢弃: {item.url[:80]}")
                continue
            seen.add(fp)
            result.append(item)
        return result

    # ------------------------------------------------------------------
    # 级2：TF-IDF 余弦相似度语义去重
    # ------------------------------------------------------------------

    def _dedup_by_content(self, items: List[CleanedItem]) -> List[CleanedItem]:
        if len(items) <= 1:
            return items

        # 构建检索文本：title 权重更高，重复两次
        corpus = [
            f"{item.title} {item.title} {item.content}"
            for item in items
        ]

        # TF-IDF 向量化
        # char_wb：字符级 n-gram，对中文无需分词，(2,4) 覆盖词根到短语
        vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 4),
            max_features=50000,
            sublinear_tf=True,
        )
        try:
            tfidf_matrix = vectorizer.fit_transform(corpus)
        except ValueError as e:
            # 语料全为空字符串时 fit_transform 会报错
            self.logger.warning(f"TF-IDF 向量化失败，跳过语义去重: {e}")
            return items

        # 计算相似度矩阵（稀疏 → 密集）
        sim_matrix = cosine_similarity(tfidf_matrix)

        n = len(items)
        duplicate: list[bool] = [False] * n

        for i in range(n):
            if duplicate[i]:
                continue
            for j in range(i + 1, n):
                if duplicate[j]:
                    continue
                if sim_matrix[i][j] >= self.threshold:
                    # 保留 pub_time 较新的一条
                    keep, drop = _newer(i, j, items)
                    duplicate[drop] = True
                    self.logger.debug(
                        f"语义重复(sim={sim_matrix[i][j]:.3f})，"
                        f"保留: {items[keep].url[:60]} | "
                        f"丢弃: {items[drop].url[:60]}"
                    )

        return [item for idx, item in enumerate(items) if not duplicate[idx]]


# ------------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------------

def _newer(i: int, j: int, items: List[CleanedItem]) -> tuple[int, int]:
    """返回 (保留索引, 丢弃索引)，pub_time 较新的保留。"""
    ti: Optional[datetime] = items[i].pub_time
    tj: Optional[datetime] = items[j].pub_time

    if ti is None and tj is None:
        return i, j          # 都没时间，保留先出现的
    if ti is None:
        return j, i          # j 有时间，保留 j
    if tj is None:
        return i, j          # i 有时间，保留 i
    return (i, j) if ti >= tj else (j, i)