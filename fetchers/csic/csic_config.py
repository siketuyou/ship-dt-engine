"""
中船集团各频道、栏目的采集配置。
新增栏目只需在对应频道的 columns 列表追加一条，无需改任何其他文件。

实测页面结构（2025-09 抓包确认）：

  首页 (index.html)：
    - 完整 HTML
    - 列表容器: <div id="comp_164"><ul><li>...</li></ul></div>
    - 分页容器: <td id="pag_164" class="pages">（JS 渲染，静态拿不到）

  翻页 (index_164_{offset}.html)：
    - 返回 HTML 片段（无 <html>/<body>）
    - 直接是 <li><a>标题</a><span>日期</span></li>
    - 编码可能是 GBK

  翻页 URL 规律：
    offset = total_pages - (page_number - 1)
    第1页 → index.html
    第2页 → index_164_{total_pages-1}.html
    末页  → index_164_1.html
"""
from dataclasses import dataclass, field

# 中船 CMS 翻页固定参数，实测确认，与 page_size 无关
PAGE_PARAM = 164


@dataclass
class Selectors:
    """一个栏目页面的 CSS 选择器集合"""
    # 列表页
    list_item: str              # 首页（完整 HTML）的列表项选择器
    list_item_fragment: str     # 翻页片段的列表项选择器
    title: str                  # 标题 <a>（含 href）
    pub_time: str               # 发布时间
    # 详情页
    body: str                   # 正文容器
    img: str = "div.article_con img"  # 正文内图片


@dataclass
class ColumnConfig:
    channel_id: str          # e.g. "n10"
    column_id:  str          # e.g. "n67"
    name:       str          # e.g. "科技创新 / 科研动态"
    page_size:  int = 10
    selectors:  Selectors = field(default_factory=lambda: Selectors(
        list_item          = "#comp_164 > ul > li",
        list_item_fragment = "li",
        title              = "a",
        pub_time           = "span",
        body               = "div.article_con",
    ))

    @property
    def list_url(self) -> str:
        """首页 URL"""
        from config.settings import settings
        return f"{settings.CSIC_BASE_URL}/{self.channel_id}/{self.column_id}/index.html"

    def page_url(self, page_index: int, total_pages: int) -> str:
        """
        第 N 页（1-based）的 URL。
        offset = total_pages - (page_index - 1)

        注意：参数是 total_pages（总页数），不是 total_articles（总文章数）。
        """
        from config.settings import settings
        if page_index == 1:
            return self.list_url
        offset = total_pages - (page_index - 1)
        return (
            f"{settings.CSIC_BASE_URL}/{self.channel_id}/{self.column_id}"
            f"/index_{PAGE_PARAM}_{offset}.html"
        )


# ════════════════════════════════════════════════
# 频道与栏目注册表
# ════════════════════════════════════════════════

_DEFAULT_SEL = Selectors(
    list_item          = "#comp_164 > ul > li",
    list_item_fragment = "li",
    title              = "a",
    pub_time           = "span",
    body               = "div.article_con",
)

CHANNELS: list[ColumnConfig] = [
    # ── 科技创新（n10）─────────────────────────
    ColumnConfig("n10", "n67", "科技创新 / 科研动态",   selectors=_DEFAULT_SEL),
    ColumnConfig("n10", "n68", "科技创新 / 科研领域",   selectors=_DEFAULT_SEL),
    ColumnConfig("n10", "n69", "科技创新 / 研究成果",   selectors=_DEFAULT_SEL),
    ColumnConfig("n10", "n70", "科技创新 / 科研院所",   selectors=_DEFAULT_SEL),

    # ── 新闻中心（n5）──────────────────────────
    ColumnConfig("n5",  "n18", "新闻中心 / 集团要闻",   selectors=_DEFAULT_SEL),
    ColumnConfig("n5",  "n19", "新闻中心 / 媒体聚焦",   selectors=_DEFAULT_SEL),
]

CHANNEL_MAP: dict[tuple[str, str], ColumnConfig] = {
    (c.channel_id, c.column_id): c for c in CHANNELS
}