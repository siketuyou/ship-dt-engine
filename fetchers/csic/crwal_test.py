#!/usr/bin/env python3
"""
独立爬虫测试脚本 —— 采集 www.cssc.net.cn/n10/n67（科技创新/科研动态）
增量时间: 2026-02-20
输出:     所有 pub_time > since 的文章标题

═══════════════════════════════════════════════════
实测页面结构（2025-09 抓包确认）
═══════════════════════════════════════════════════

首页 (index.html):
  - 完整 HTML，包含 <head>/<body>
  - 列表容器: <div id="comp_164"><ul><li>...</li></ul></div>
  - 分页容器: <td id="pag_164" class="pages">（JS 渲染，静态 HTML 拿不到）

翻页 (index_164_{offset}.html):
  - 返回 HTML **片段**（无 <html>/<head>/<body>）
  - 直接是 <li><a>...</a><span>日期</span></li> 列表
  - 编码可能是 GBK/GB2312（Content-Type 未声明或声明 utf-8 但实际不是）

翻页 URL 规律:
  分页文本 "总页数:5"  →  total_pages = 5
  第1页  → index.html
  第2页  → index_164_4.html   (offset = 5 - 1 = 4)
  第3页  → index_164_3.html   (offset = 5 - 2 = 3)
  第5页  → index_164_1.html   (offset = 5 - 4 = 1)
  即 offset = total_pages - (page_number - 1)

使用方法:
    pip install requests beautifulsoup4 lxml
    python test_crawl_n10_n67.py
"""

import re
import sys
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ════════════════════════════════════════════════
# 配置
# ════════════════════════════════════════════════
BASE_URL    = "http://www.cssc.net.cn"
CHANNEL_ID  = "n10"
COLUMN_ID   = "n67"
COLUMN_NAME = "科技创新 / 科研动态"
PAGE_PARAM  = 164                    # 中船 CMS 固定翻页参数，与 page_size 无关

SINCE = datetime(2020, 2, 20)        # 增量水位线

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "http://www.cssc.net.cn/",
}

# ── CSS 选择器 ─────────────────────────────────
# 首页：完整 HTML，列表在 <div id="comp_164"><ul><li>
SEL_LIST_ITEM_FULL = "#comp_164 > ul > li"
# 翻页片段：无外层容器，直接是 <li> 列表
SEL_LIST_ITEM_FRAG = "li"
SEL_TITLE    = "a"
SEL_PUB_TIME = "span"          # <span>2025-09-24</span>，无 class

TIMEOUT = 15
ENCODINGS_TRY = ["utf-8", "gbk", "gb2312", "gb18030"]


# ════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════
def parse_time(text: str) -> datetime | None:
    """多格式时间解析"""
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%Y年%m月%d日", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def smart_decode(resp: requests.Response) -> str:
    """
    智能解码响应体。
    翻页片段可能 Content-Type 声明 utf-8 但实际是 GBK，需要逐一尝试。
    """
    # 1) 从 Content-Type 取编码
    ct = resp.headers.get("Content-Type", "")
    m = re.search(r"charset=([\w-]+)", ct, re.IGNORECASE)
    if m:
        try:
            return resp.content.decode(m.group(1))
        except (UnicodeDecodeError, LookupError):
            pass

    # 2) 从 HTML meta 标签取编码
    m = re.search(rb'charset=["\']?([\w-]+)', resp.content[:2048], re.IGNORECASE)
    if m:
        try:
            return resp.content.decode(m.group(1).decode("ascii", errors="ignore"))
        except (UnicodeDecodeError, LookupError):
            pass

    # 3) 逐一尝试常见编码
    for enc in ENCODINGS_TRY:
        try:
            return resp.content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue

    # 4) 兜底
    return resp.content.decode("utf-8", errors="replace")


def get(url: str) -> requests.Response:
    """带 Headers 的 GET 请求"""
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp


def get_total_pages(soup: BeautifulSoup) -> int:
    """
    从首页 HTML 提取总页数。

    分页区域是 JS 渲染的，静态解析可能拿不到。
    策略：
      1) 找 <td id="pag_164"> 中的 "总页数:N"
      2) 找 JS 源码中的 totalPage 变量
      3) 降级：返回 1
    """
    # 方法 1：分页容器文本
    pag = soup.select_one("#pag_164, td.pages")
    if pag:
        m = re.search(r"总页数[：:]\s*(\d+)", pag.get_text())
        if m:
            return int(m.group(1))

    # 方法 2：从 <script> 中提取 totalPage / pageCount
    for script in soup.find_all("script"):
        text = script.string or ""
        m = re.search(r"(?:totalPage|pageCount|total_pages?)\s*[=:]\s*(\d+)", text)
        if m:
            return int(m.group(1))
    # 降级
    return 1


def build_page_url(page: int, total_pages: int) -> str:
    """
    构造第 page 页的 URL（1-based）。
    offset = total_pages - (page - 1)
    """
    if page == 1:
        return f"{BASE_URL}/{CHANNEL_ID}/{COLUMN_ID}/index.html"
    offset = total_pages - (page - 1)
    return f"{BASE_URL}/{CHANNEL_ID}/{COLUMN_ID}/index_{PAGE_PARAM}_{offset}.html"


def parse_items(soup: BeautifulSoup, is_fragment: bool = False) -> list[dict]:
    """
    从 soup 中提取文章列表。

    is_fragment=True  → 翻页片段，直接选 <li>
    is_fragment=False → 首页完整 HTML，选 #comp_164 > ul > li
    """
    if is_fragment:
        items = soup.select(SEL_LIST_ITEM_FRAG)
    else:
        items = soup.select(SEL_LIST_ITEM_FULL)
        # 首页选择器失效时降级
        if not items:
            items = soup.select(SEL_LIST_ITEM_FRAG)

    results = []
    for item in items:
        title_tag = item.select_one(SEL_TITLE)
        time_tag  = item.select_one(SEL_PUB_TIME)
        if not title_tag:
            continue

        title = title_tag.get_text(strip=True)
        href = title_tag.get("href", "")
        if not isinstance(href, str) or not href:
            continue

        url = urljoin(BASE_URL + "/", href)
        pub_text = time_tag.get_text(strip=True) if time_tag else ""
        pub_time = parse_time(pub_text)

        results.append({
            "title": title,
            "url": url,
            "pub_time": pub_time,
            "pub_time_str": pub_time.strftime("%Y-%m-%d") if pub_time else "未知",
        })
    return results


# ════════════════════════════════════════════════
# 主逻辑
# ════════════════════════════════════════════════
def main():
    print(f"{'='*64}")
    print(f"  栏目 : {COLUMN_NAME}")
    print(f"  URL  : {BASE_URL}/{CHANNEL_ID}/{COLUMN_ID}/index.html")
    print(f"  since: {SINCE.strftime('%Y-%m-%d')}")
    print(f"{'='*64}\n")

    # ── Step 1: 请求首页 ─────────────────────────
    first_url = build_page_url(page=1, total_pages=0)
    print(f"[页 1] 请求首页: {first_url}")
    try:
        resp = get(first_url)
    except Exception as e:
        print(f"  ✘ 首页请求失败: {e}")
        sys.exit(1)

    html = smart_decode(resp)
    soup = BeautifulSoup(html, "lxml")

    total_pages = get_total_pages(soup)
    print(f"  总页数: {total_pages}\n")

    # ── Step 2: 逐页遍历 ─────────────────────────
    collected: list[dict] = []
    stop = False

    for page_num in range(1, total_pages + 1):
        if stop:
            break

        is_fragment = False

        if page_num > 1:
            page_url = build_page_url(page=page_num, total_pages=total_pages)
            print(f"[页 {page_num}] 请求: {page_url}")
            try:
                resp = get(page_url)
            except Exception as e:
                print(f"  ✘ 请求失败，跳过: {e}")
                continue
            html = smart_decode(resp)
            soup = BeautifulSoup(html, "lxml")
            is_fragment = True
        else:
            print(f"[页 1] 解析首页列表...")

        items = parse_items(soup, is_fragment=is_fragment)
        if not items:
            print(f"  ⚠ 列表为空，停止遍历")
            break

        page_count = 0
        for art in items:
            pub_time = art["pub_time"]

            # 增量判断：遇到 ≤ since 的文章即停止（列表时间倒序）
            if pub_time and pub_time <= SINCE:
                print(f"  ⏹ 水位线命中: {art['pub_time_str']} ≤ {SINCE.strftime('%Y-%m-%d')}，停止")
                stop = True
                break

            collected.append(art)
            page_count += 1

        print(f"  本页采集: {page_count} 条")

    # ── Step 3: 输出结果 ─────────────────────────
    print(f"\n{'='*64}")
    print(f"  采集完成: 共 {len(collected)} 篇 (pub_time > {SINCE.strftime('%Y-%m-%d')})")
    print(f"{'='*64}\n")

    if not collected:
        print("  （无符合条件的文章）\n")
    else:
        for i, art in enumerate(collected, 1):
            print(f"  {i:3d}. [{art['pub_time_str']}]  {art['title']}")
            print(f"       {art['url']}")
        print()

    return collected


if __name__ == "__main__":
    main()