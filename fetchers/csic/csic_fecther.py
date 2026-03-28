import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 导入你提供的模型和配置
from models.schemas import RawArticle
from storage.state_store import StateStore
from fetchers.base_fetcher import BaseFetcher
from fetchers.csic.csic_config import CHANNELS, ColumnConfig, Selectors

class CsicFetcher(BaseFetcher):
    """
    中国船舶集团 (CSSC) 综合采集器
    基于栏目配置表 (CHANNELS) 自动遍历多个频道与栏目，并采集详情页正文。
    """

    ENCODINGS_TRY = ["utf-8", "gbk", "gb2312", "gb18030"]

    def __init__(self, state_store: StateStore):
        super().__init__(state_store)
        self.source_name = "csic_news"  # 全局唯一标识
        
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "http://www.cssc.net.cn/",
        }

    @property
    def _base_url(self) -> str:
        """取配置中的第一个栏目作为连通性测试的目标"""
        if CHANNELS:
            return CHANNELS[0].list_url
        return "http://www.cssc.net.cn/"

    def fetch(self, since: Optional[datetime] = None) -> list[RawArticle]:
        """遍历所有配置的栏目进行抓取"""
        self.logger.info(f"[{self.source_name}] 启动全局抓取，水位线: {since}，共 {len(CHANNELS)} 个栏目")
        
        all_articles: list[RawArticle] = []
        
        for col_config in CHANNELS:
            self.logger.info(f"[{self.source_name}] 开始采集栏目: {col_config.name} ({col_config.channel_id}/{col_config.column_id})")
            try:
                col_articles = self._fetch_column(col_config, since)
                all_articles.extend(col_articles)
            except Exception as e:
                self.logger.error(f"[{self.source_name}] 栏目 {col_config.name} 采集异常: {e}")
                continue

        return all_articles

    def _fetch_column(self, config: ColumnConfig, since: Optional[datetime]) -> list[RawArticle]:
        """处理单个栏目的翻页与详情抓取"""
        collected = []
        
        # ── Step 1: 请求首页并获取总页数 ──
        try:
            resp = self.http.get(config.list_url, headers=self.headers)
            resp.raise_for_status()
        except Exception as e:
            self.logger.warning(f"[{self.source_name}] 首页请求失败 ({config.list_url}): {e}")
            return collected

        html = self._smart_decode(resp)
        soup = BeautifulSoup(html, "lxml")
        total_pages = self._get_total_pages(soup)
        self.logger.debug(f"[{self.source_name}] {config.name} 解析到总页数: {total_pages}")

        # ── Step 2: 逐页遍历列表 ──
        stop_crawling = False
        
        for page_num in range(1, total_pages + 1):
            if stop_crawling:
                break

            is_fragment = False
            if page_num > 1:
                page_url = config.page_url(page_num, total_pages)
                try:
                    resp = self.http.get(page_url, headers=self.headers)
                    resp.raise_for_status()
                    html = self._smart_decode(resp)
                    soup = BeautifulSoup(html, "lxml")
                    is_fragment = True
                except Exception as e:
                    self.logger.warning(f"[{self.source_name}] 第 {page_num} 页请求失败，跳过: {e}")
                    continue

            # 提取列表项
            items = self._parse_list_items(soup, config.selectors, is_fragment)
            if not items:
                break

            for item in items:
                pub_time = item["pub_time"]

                # 【核心策略】：在发起耗时的详情页请求前，先进行增量水位线判断
                if since and pub_time and pub_time <= since:
                    self.logger.info(f"[{self.source_name}] {config.name} 命中水位线 ({pub_time} <= {since})，本栏目停止")
                    stop_crawling = True
                    break

                # ── Step 3: 下钻获取详情页正文与图片 ──
                content, img_urls = self._fetch_detail(item["url"], config.selectors)

                article = RawArticle(
                    source=self.source_name,
                    url=item["url"],
                    title=item["title"],
                    content=content,
                    pub_time=pub_time,
                    img_urls=img_urls,
                    # video_urls 暂留空，若需解析视频可类似 img_urls 补充逻辑
                )
                collected.append(article)

        return collected

    def _fetch_detail(self, url: str, selectors: Selectors) -> tuple[str, list[str]]:
        """增强版：使用多个候选 Class/ID 提取正文，对抗 CMS 模板碎片化"""
        try:
            resp = self.http.get(url, headers=self.headers)
            resp.raise_for_status()
            html = self._smart_decode(resp)
            soup = BeautifulSoup(html, "lxml")
            
            # 国内政企 CMS 常见正文容器列表（按优先级排序）
            fallback_body_selectors = [
                selectors.body,           # 配置中传入的默认值 (div.article_con)
                "div.Custom_UnionStyle",  # TRS CMS 常见编辑器类名
                "div.TRS_Editor",         # TRS CMS 原生类名
                "div.con_txt",            
                "div#zoom",               
                "div.content",
                "div.article-content",
                "div.Section0"
            ]

            body_tag = None
            for sel in fallback_body_selectors:
                body_tag = soup.select_one(sel)
                if body_tag:
                    break
            
            content = body_tag.get_text(separator="\n", strip=True) if body_tag else ""
            
            img_urls = []
            if body_tag:
                for img in body_tag.select("img"):
                    src = img.get("src")
                    if src:
                        img_urls.append(urljoin(url, src))
                        
            return content, img_urls
            
        except Exception as e:
            self.logger.warning(f"[{self.source_name}] 详情页提取失败 ({url}): {e}")
            return "", []
    # =========================================================================
    # 通用辅助方法 (解码、时间解析、总页数解析)
    # =========================================================================

    def _smart_decode(self, resp) -> str:
        ct = resp.headers.get("Content-Type", "")
        m = re.search(r"charset=([\w-]+)", ct, re.IGNORECASE)
        if m:
            try: return resp.content.decode(m.group(1))
            except: pass

        m = re.search(rb'charset=["\']?([\w-]+)', resp.content[:2048], re.IGNORECASE)
        if m:
            try: return resp.content.decode(m.group(1).decode("ascii", errors="ignore"))
            except: pass

        for enc in self.ENCODINGS_TRY:
            try: return resp.content.decode(enc)
            except: continue

        return resp.content.decode("utf-8", errors="replace")

    def _get_total_pages(self, soup: BeautifulSoup) -> int:
        pag = soup.select_one("#pag_164, td.pages")
        if pag:
            m = re.search(r"总页数[：:]\s*(\d+)", pag.get_text())
            if m: return int(m.group(1))

        for script in soup.find_all("script"):
            text = script.string or ""
            m = re.search(r"(?:totalPage|pageCount|total_pages?)\s*[=:]\s*(\d+)", text)
            if m: return int(m.group(1))
        return 1

    def _parse_time(self, text: str) -> Optional[datetime]:
        text = text.strip()
        for fmt in ("%Y-%m-%d", "%Y年%m月%d日", "%Y/%m/%d", "%Y.%m.%d"):
            try: return datetime.strptime(text, fmt)
            except ValueError: continue
        return None

    def _parse_list_items(self, soup: BeautifulSoup, selectors: Selectors, is_fragment: bool) -> list[dict]:
        """增强版：支持动态 comp_id 解析，添加脏数据过滤与正则时间兜底"""
        if is_fragment:
            items = soup.select(selectors.list_item_fragment)
        else:
            # 1. 尝试配置中的默认选择器
            items = soup.select(selectors.list_item)
            # 2. 【核心修复】尝试使用 CSS 前缀匹配，解决 comp_ID 不同的问题
            if not items:
                items = soup.select("div[id^='comp_'] > ul > li")
            # 3. 终极兜底
            if not items:
                items = soup.select(selectors.list_item_fragment)

        results = []
        for item in items:
            title_tag = item.select_one(selectors.title)
            if not title_tag:
                continue

            href = title_tag.get("href", "")
            if not isinstance(href, str) or not href or "javascript" in href:
                continue
            
            # 【核心修复】过滤掉非文章的导航链接 (通常真正的文章链接会包含 /c 或 content.html)
            if "/c" not in href and "content.html" not in href:
                continue

            from config.settings import settings
            url = urljoin(settings.CSIC_BASE_URL + "/", href)
            
            # 尝试优先从 span 提取时间
            time_tag = item.select_one(selectors.pub_time)
            pub_text = time_tag.get_text(strip=True) if time_tag else ""
            pub_time = self._parse_time(pub_text)

            # 【核心修复】如果 span 提取不到，直接对整个 li 文本使用正则爆破提取日期
            if not pub_time:
                m = re.search(r"20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}", item.get_text())
                if m:
                    pub_time = self._parse_time(m.group(0))

            # 强制过滤掉实在没有时间的垃圾数据，防止击穿水位线
            if not pub_time:
                continue

            results.append({
                "title": title_tag.get_text(strip=True),
                "url": url,
                "pub_time": pub_time,
            })
        return results