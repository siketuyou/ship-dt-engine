"""
清洗器（Cleaner）—— 流水线第二道工序。

输入 : List[FilteredItem]  过滤器输出
输出 : List[CleanedItem]   清洗后的标准条目

清洗步骤：
  1. url_fingerprint  sha256(url) 用于后续去重
  2. title 清洗       去除首尾空白、合并内部连续空白、去除零宽字符
  3. content 清洗     去除 HTML 残留标签、合并连续空行、去除零宽/控制字符、
                      去除导航/版权等噪声行
  4. 空内容兜底       content 清洗后为空则用 title 填充，避免空条目下传
"""
from __future__ import annotations

import hashlib
import re
from typing import List

from models.schemas import CleanedItem,FilteredItem
from utils.logger import get_logger

# 噪声行特征：命中则整行丢弃
_NOISE_PATTERNS: list[re.Pattern] = [
    re.compile(p) for p in [
        r"^(版权所有|copyright|all rights reserved)",   # 版权声明
        r"^(来源|source)[：:]\s*$",                     # 空来源行
        r"^(责任编辑|编辑|记者)[：:]\s*\S{0,10}$",      # 编辑署名行
        r"^[\s\-—_=*#]{3,}$",                          # 纯分隔线
        r"^(分享|转发|收藏|点赞|阅读量|浏览)[：:\d]",    # 社交操作行
        r"^\[.*?\]$",                                   # 纯方括号内容
    ]
]

# 零宽及不可见控制字符
_INVISIBLE = re.compile(r"[\u200b\u200c\u200d\ufeff\u00ad\x00-\x08\x0b\x0c\x0e-\x1f]")

# 残留 HTML 标签
_HTML_TAG = re.compile(r"<[^>]+>")

# 连续空行压缩（3行以上 → 2行）
_MULTI_BLANK = re.compile(r"\n{3,}")


class ArticleCleaner:

    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def run(self, items: List[FilteredItem]) -> List[CleanedItem]:
        result: List[CleanedItem] = []
        for item in items:
            try:
                cleaned = self._clean_one(item)
                result.append(cleaned)
            except Exception as e:
                self.logger.warning(f"清洗失败，跳过: {item.article.url[:80]} | {e}")
        self.logger.info(f"清洗完成：输入={len(items)} 输出={len(result)}")
        return result

    # ------------------------------------------------------------------
    # 单条清洗
    # ------------------------------------------------------------------

    def _clean_one(self, item: FilteredItem) -> CleanedItem:
        a = item.article
        title   = self._clean_title(a.title or "")
        content = self._clean_content(a.content or "")

        # content 清洗后为空，用 title 兜底
        if not content:
            content = title
            self.logger.debug(f"content 为空，用 title 兜底: {a.url[:80]}")

        return CleanedItem(
            source           = a.source,
            url              = a.url,
            url_fingerprint  = _sha256(a.url),
            title            = title,
            content          = content,
            pub_time         = a.pub_time,
            img_urls         = a.img_urls,
            video_urls       = a.video_urls,
            raw_location     = a.raw_location,
            fetched_at       = a.fetched_at,
        )

    # ------------------------------------------------------------------
    # title 清洗
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_title(title: str) -> str:
        title = _INVISIBLE.sub("", title)          # 去零宽字符
        title = re.sub(r"\s+", " ", title).strip() # 合并空白
        return title

    # ------------------------------------------------------------------
    # content 清洗
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_content(content: str) -> str:
        content = _HTML_TAG.sub("", content)        # 去残留 HTML 标签
        content = _INVISIBLE.sub("", content)       # 去零宽/控制字符

        lines = content.splitlines()
        cleaned_lines: list[str] = []
        for line in lines:
            line = re.sub(r"[ \t]+", " ", line).strip()   # 行内合并空白
            if not line:
                cleaned_lines.append("")
                continue
            if _is_noise(line):
                continue
            cleaned_lines.append(line)

        content = "\n".join(cleaned_lines)
        content = _MULTI_BLANK.sub("\n\n", content) # 连续空行压缩
        return content.strip()


# ------------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------------

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_noise(line: str) -> bool:
    low = line.lower()
    return any(p.search(low) for p in _NOISE_PATTERNS)