import re
import sys
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models.schemas import RawArticle
from fetchers.base_fetcher import BaseFetcher
from fetchers.csic.csic_config import CHANNELS, ColumnConfig, Selectors
from config.settings import settings


class CsicFetcher(BaseFetcher):
    """
    中国船舶集团 (CSSC) 综合采集器
    基于栏目配置表 (CHANNELS) 自动遍历多个频道与栏目，并采集详情页正文。
    """

    ENCODINGS_TRY = ["utf-8", "gbk", "gb2312", "gb18030"]

    def __init__(self, model_id: int, db_manager):
        # ── 对齐新基类签名 ──
        super().__init__(model_id, db_manager)

        # http client 由子类自己管理（基类未提供）
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "http://www.cssc.net.cn/",
        })

    # =========================================================================
    # 实现基类抽象方法
    # =========================================================================

    def _run_spider(self, since_time: datetime) -> list[RawArticle]:
        """
        遍历所有配置的栏目进行抓取，由 BaseFetcher.fetch_all() 调用。
        since_time 为所有关键词中最低的水位线。
        """
        self.logger.info(
            f"[csic] 启动全局抓取，水位线: {since_time}，共 {len(CHANNELS)} 个栏目"
        )

        all_articles: list[RawArticle] = []

        for col_config in CHANNELS:
            self.logger.info(
                f"[csic] 开始采集栏目: {col_config.name} "
                f"({col_config.channel_id}/{col_config.column_id})"
            )
            try:
                col_articles = self._fetch_column(col_config, since_time)
                all_articles.extend(col_articles)
            except Exception as e:
                self.logger.error(f"[csic] 栏目 {col_config.name} 采集异常: {e}")
                continue

        return all_articles

    # =========================================================================
    # 内部实现
    # =========================================================================
    def _fetch_column(self, config: ColumnConfig, since: Optional[datetime]) -> list[RawArticle]:
        collected = []

        # Step 1: 请求首页，只用来解析总页数，不解析列表
        try:
            resp = self.http.get(config.list_url)
            resp.raise_for_status()
        except Exception as e:
            self.logger.warning(f"[csic] 首页请求失败 ({config.list_url}): {e}")
            return collected

        html = self._smart_decode(resp)
        soup = BeautifulSoup(html, "lxml")
        total_pages, page_param = self._get_page_info(soup)

        if not page_param:
            self.logger.warning(f"[csic] {config.name} 无法解析 page_param，跳过")
            return collected

        self.logger.info(f"[csic] {config.name} 总页数={total_pages} page_param={page_param}")

        # Step 2: 从第1页翻页片段开始遍历（首页列表是 JS 渲染，片段才有真实数据）
        # 第1页片段 offset = total_pages，即 index_{param}_{total_pages}.html
        stop_crawling = False
        # 首页静态列表先解析（片段从第2页开始）
        items = self._parse_list_items(soup, config.selectors, is_fragment=False)
        for item in items:
            pub_time = item["pub_time"]
            if since and pub_time and pub_time <= since:
                stop_crawling = True
                break
            content, img_urls = self._fetch_detail(item["url"], config.selectors)
            collected.append(RawArticle(
                model_id=self.model_id,
                keyword_id=None,
                source="csic_news",
                url=item["url"],
                title=item["title"],
                content=content,
                pub_time=pub_time,
                img_urls=img_urls,
            ))

        for page_num in range(2, total_pages + 1):
            if stop_crawling:
                break

            # 所有页都用片段 URL（包括第1页）
            offset = total_pages - (page_num - 1)
            frag_url = (
                f"{settings.CSIC_BASE_URL}/{config.channel_id}/{config.column_id}"
                f"/index_{page_param}_{offset}.html"
            )
            try:
                resp = self.http.get(frag_url)
                resp.raise_for_status()
                html = self._smart_decode(resp)
                frag_soup = BeautifulSoup(html, "lxml")
            except Exception as e:
                self.logger.warning(f"[csic] 第{page_num}页片段请求失败，跳过: {e}")
                continue

            items = self._parse_list_items(frag_soup, config.selectors, is_fragment=True)
            if not items:
                self.logger.debug(f"[csic] 第{page_num}页无条目，停止")
                break

            for item in items:
                pub_time = item["pub_time"]
                if since and pub_time and pub_time <= since:
                    self.logger.info(
                        f"[csic] {config.name} 命中水位线 ({pub_time} <= {since})，停止"
                    )
                    stop_crawling = True
                    break

                content, img_urls = self._fetch_detail(item["url"], config.selectors)
                article = RawArticle(
                    model_id=self.model_id,
                    keyword_id=None,
                    source="csic_news",
                    url=item["url"],
                    title=item["title"],
                    content=content,
                    pub_time=pub_time,
                    img_urls=img_urls,
                )
                collected.append(article)

        return collected
    def _fetch_detail(
        self, url: str, selectors: Selectors
    ) -> tuple[str, list[str]]:
        """增强版：使用多个候选 Class/ID 提取正文，对抗 CMS 模板碎片化"""
        try:
            resp = self.http.get(url)
            resp.raise_for_status()
            html = self._smart_decode(resp)
            soup = BeautifulSoup(html, "lxml")

            fallback_body_selectors = [
                selectors.body,
                "div.Custom_UnionStyle",
                "div.TRS_Editor",
                "div.con_txt",
                "div#zoom",
                "div.content",
                "div.article-content",
                "div.Section0",
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
                        img_urls.append(urljoin(url, str(src)))

            return content, img_urls

        except Exception as e:
            self.logger.warning(f"[csic] 详情页提取失败 ({url}): {e}")
            return "", []

    # =========================================================================
    # 通用辅助方法
    # =========================================================================

    def _smart_decode(self, resp) -> str:
        ct = resp.headers.get("Content-Type", "")
        m = re.search(r"charset=([\w-]+)", ct, re.IGNORECASE)
        if m:
            try:
                return resp.content.decode(m.group(1))
            except Exception:
                pass

        m = re.search(rb"charset=[\"']?([\w-]+)", resp.content[:2048], re.IGNORECASE)
        if m:
            try:
                return resp.content.decode(
                    m.group(1).decode("ascii", errors="ignore")
                )
            except Exception:
                pass

        for enc in self.ENCODINGS_TRY:
            try:
                return resp.content.decode(enc)
            except Exception:
                continue

        return resp.content.decode("utf-8", errors="replace")

    def _get_page_info(self, soup: BeautifulSoup) -> tuple[int, str]:
        for script in soup.find_all("script"):
            text = script.string or ""
            # 真实总页数在 cookie 赋值里：document.cookie="maxPageNum6204=218"
            m_pages = re.search(r'document\.cookie\s*=\s*"maxPageNum\d+=(\d+)"', text)
            m_param = re.search(r'var\s+purl\s*=\s*["\'].*?index_(\d+)["\']', text)
            if m_pages and m_param:
                return int(m_pages.group(1)), m_param.group(1)
        return 1, ""

    def _parse_time(self, text: str) -> Optional[datetime]:
        text = text.strip()
        for fmt in ("%Y-%m-%d", "%Y年%m月%d日", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    def _parse_list_items(
        self, soup: BeautifulSoup, selectors: Selectors, is_fragment: bool
    ) -> list[dict]:
        """增强版：支持动态 comp_id 解析，添加脏数据过滤与正则时间兜底"""
        if is_fragment:
            items = soup.select(selectors.list_item_fragment)
        else:
            items = soup.select(selectors.list_item)
            if not items:
                items = soup.select("div[id^='comp_'] > ul > li")
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

            if "/c" not in href and "content.html" not in href:
                continue

            url = urljoin(settings.CSIC_BASE_URL + "/", href)

            time_tag = item.select_one(selectors.pub_time)
            pub_text = time_tag.get_text(strip=True) if time_tag else ""
            pub_time = self._parse_time(pub_text)

            if not pub_time:
                m = re.search(
                    r"20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}", item.get_text()
                )
                if m:
                    pub_time = self._parse_time(m.group(0))

            if not pub_time:
                continue

            results.append({
                "title": title_tag.get_text(strip=True),
                "url": url,
                "pub_time": pub_time,
            })
        return results