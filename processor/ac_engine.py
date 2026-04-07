"""
AC 自动机封装 + 语义向量兜底匹配。
将一组 {keyword_id: keyword_name} 编译成 Aho-Corasick 自动机，models/paraphrase-multilingual-MiniLM-L12-v2
search() 返回文本中命中的所有 keyword_id（去重）。

依赖：pip install pyahocorasick sentence-transformers
"""
from __future__ import annotations
from typing import Dict, List, Optional
import numpy as np


class KeywordAC:
    """
    线程安全（只读）的 AC 自动机。
    构造一次，在整个 model 的过滤批次中复用。
    """

    def __init__(self, keyword_map: Dict[int, str]):
        import ahocorasick
        self._automaton = ahocorasick.Automaton()
        for kid, kname in keyword_map.items():
            if not kname:
                continue
            if kname in self._automaton:
                self._automaton.get(kname).append(kid)
            else:
                self._automaton.add_word(kname, [kid])
        self._automaton.make_automaton()
        self._empty = len(keyword_map) == 0

    def search(self, text: str) -> List[int]:
        if self._empty or not text:
            return []
        matched: set = set()
        for _end_idx, keyword_ids in self._automaton.iter(text):
            matched.update(keyword_ids)
        return sorted(matched)

    @classmethod
    def build(cls, keyword_map: Dict[int, str]) -> "KeywordAC":
        return cls(keyword_map)


class SemanticMatcher:
    """
    基于 Sentence-BERT 的语义向量兜底匹配。
    AC 未命中时调用，对「文本片段 vs 关键词」做余弦相似度打分。

    策略：
      - 将正文按句子切分（防止长文稀释相似度）
      - 每个句子与全部关键词向量做 batch 余弦相似度
      - 任意句子与某关键词相似度 >= threshold，则认为命中该关键词
    """

    # 推荐模型：多语言、中英混合效果好，模型约 120MB
    DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
    DEFAULT_MODEL_DIR = "./models/paraphrase-multilingual-MiniLM-L12-v2"
    def __init__(
        self,
        keyword_map: Dict[int, str],
        model_dir: str = DEFAULT_MODEL_DIR,
        threshold: float = 0.65,
        max_sentences: int = 40,     # 最多取前 N 句，防止超长文本拖慢速度
    ):
        from sentence_transformers import SentenceTransformer
        self._threshold     = threshold
        self._max_sentences = max_sentences
        self._empty         = not keyword_map

        if self._empty:
            return

        # {keyword_id -> keyword_name}，保留顺序用于对齐向量
        self._kid_list:  List[int] = []
        self._kname_list: List[str] = []
        for kid, kname in keyword_map.items():
            if kname:
                self._kid_list.append(kid)
                self._kname_list.append(kname)

        self._model = SentenceTransformer(model_dir)

        # 预计算关键词向量，shape: (num_keywords, hidden_dim)
        self._kw_embeddings: np.ndarray = self._model.encode(
            self._kname_list,
            normalize_embeddings=True,   # 归一化后点积 = 余弦相似度
            show_progress_bar=False,
        )

    def search(self, text: str) -> List[int]:
        """
        返回语义命中的 keyword_id 列表（去重、升序）。
        text 为空或无关键词时返回 []。
        """
        if self._empty or not text:
            return []

        sentences = self._split_sentences(text)[: self._max_sentences]
        if not sentences:
            return []

        # 编码全部句子，shape: (num_sentences, hidden_dim)
        sent_embeddings: np.ndarray = self._model.encode(
            sentences,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        # 相似度矩阵，shape: (num_sentences, num_keywords)
        sim_matrix = sent_embeddings @ self._kw_embeddings.T  # 矩阵乘法，快

        # 每个关键词取最高句子分数
        max_scores = sim_matrix.max(axis=0)   # shape: (num_keywords,)

        matched_ids = [
            self._kid_list[i]
            for i, score in enumerate(max_scores)
            if score >= self._threshold
        ]
        return sorted(matched_ids)

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """
        简单句子切分：按标点 + 换行，过滤空串和极短片段（< 5字）。
        """
        import re
        parts = re.split(r"[。！？\n\.!?]+", text)
        return [p.strip() for p in parts if len(p.strip()) >= 5]

    @classmethod
    def build(
        cls,
        keyword_map: Dict[int, str],
        model_dir: str = DEFAULT_MODEL_DIR,
        threshold: float = 0.65,
    ) -> "SemanticMatcher":
        return cls(keyword_map, model_dir=model_dir, threshold=threshold)