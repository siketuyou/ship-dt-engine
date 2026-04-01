"""
AC 自动机封装。
将一组 {keyword_id: keyword_name} 编译成 Aho-Corasick 自动机，
search() 返回文本中命中的所有 keyword_id（去重）。

依赖：pip install pyahocorasick
"""
from __future__ import annotations
from typing import Dict, List


class KeywordAC:
    """
    线程安全（只读）的 AC 自动机。
    构造一次，在整个 model 的过滤批次中复用。
    """

    def __init__(self, keyword_map: Dict[int, str]):
        """
        keyword_map: {keyword_id -> keyword_name}
        keyword_name 可以是中文，pyahocorasick 原生支持 Unicode。
        """
        import ahocorasick  # 延迟导入，方便在没装包时给出清晰报错
        self._automaton = ahocorasick.Automaton()
        for kid, kname in keyword_map.items():
            if not kname:
                continue
            # 同一词可能对应多个 id，以 list 存储
            if kname in self._automaton:
                self._automaton.get(kname).append(kid)
            else:
                self._automaton.add_word(kname, [kid])
        self._automaton.make_automaton()
        self._empty = len(keyword_map) == 0

    def search(self, text: str) -> List[int]:
        """
        在 text 中搜索所有关键词，返回命中的 keyword_id 列表（去重、升序）。
        text 为空或自动机为空时返回 []。
        """
        if self._empty or not text:
            return []
        matched: set = set()
        for _end_idx, keyword_ids in self._automaton.iter(text):
            matched.update(keyword_ids)
        return sorted(matched)

    @classmethod
    def build(cls, keyword_map: Dict[int, str]) -> "KeywordAC":
        return cls(keyword_map)