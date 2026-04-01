import logging
import sys
from pathlib import Path
from datetime import datetime

# 确保从任意工作目录运行时，都能导入项目根包
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 如果放在独立文件中，请取消注释下面的导入
from config.settings import settings
from fetchers.csic.csic_fetcher import CsicFetcher
from fetchers.csic.csic_config import CHANNELS

# ── 1. 模拟依赖 (方便独立测试) ─────────────────────────
class MockDbManager:
    """用于本地测试的虚拟数据库接口，适配 BaseFetcher 依赖的方法。"""

    def __init__(self):
        self._keywords = [
            {
                "id": idx + 1,
                "keyword": cfg.name,
                "keyword_name": cfg.name,
                "incremental_spider_time": datetime(2025, 3, 26),
            }
            for idx, cfg in enumerate(CHANNELS)
        ]

    def get_model_config(self, model_id: int):
        return {"m_reptile_model_name": "csic_news"}

    def get_keywords_by_model(self, model_id: int):
        return self._keywords

    def get_keyword_info(self, keyword_id: int):
        for kw in self._keywords:
            if kw["id"] == keyword_id:
                return kw
        return self._keywords[0]


# ── 2. 主测试函数 ────────────────────────────────────
def main():
    # 配置基础的日志输出，方便在控制台看到抓取过程
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    print("=" * 70)
    print(" 🚀 开始测试 CsicFetcher (多栏目增量 + 详情页抓取)")
    print("=" * 70)

    # 初始化依赖与采集器
    settings.CSIC_BASE_URL = "http://www.cssc.net.cn"
    db_manager = MockDbManager()
    fetcher = CsicFetcher(model_id=1, db_manager=db_manager)

    # 设定题目要求的水位线：2022-06-06
    since_date = datetime(2025, 3, 26)
    print(f"[*] 设定的全局水位线 (since): {since_date.strftime('%Y-%m-%d')}\n")

    # 执行抓取
    try:
        articles = fetcher.fetch_all()
    except Exception as e:
        print(f"\n[!] 抓取过程中发生致命异常: {e}")
        return

    # ── 3. 打印结果报表 ─────────────────────────────────
    print("\n" + "=" * 70)
    print(f" ✅ 测试完成，共抓取到 {len(articles)} 篇有效文章")
    print("=" * 70)

    if not articles:
        print("未找到符合条件的新文章。")
        return

    # 遍历打印采集结果，展示核心字段验证效果
    for i, art in enumerate(articles, 1):
        pub_time_str = art.pub_time.strftime('%Y-%m-%d') if art.pub_time else "未知时间"
        print(f"{i:3d}. [{pub_time_str}] {art.title}")
        print(f"     🔗 链接: {art.url}")
        if art.img_urls:
            print(f"     🖼️ 图片: 包含 {len(art.img_urls)} 张图")
            # 打印第一张图片链接作为抽查
            print(f"             首图 -> {art.img_urls[0]}")
        print("-" * 50)


if __name__ == "__main__":
    main()