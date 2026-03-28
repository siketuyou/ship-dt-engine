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
from fetchers.csic.csic_fecther import CsicFetcher

# ── 1. 模拟依赖 (方便独立测试) ─────────────────────────
class MockStateStore:
    """用于本地测试的虚拟状态存储，避免连接真实数据库"""
    def get_last_fetch_time(self, source_name: str):
        return None
    
    def update_last_fetch_time(self, source_name: str):
        pass


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
    state_store = MockStateStore()
    fetcher = CsicFetcher(state_store=state_store)

    # 设定题目要求的水位线：2022-06-06
    since_date = datetime(2025, 3, 26)
    print(f"[*] 设定的全局水位线 (since): {since_date.strftime('%Y-%m-%d')}\n")

    # 测试目标网站连通性
    print("[*] 正在测试目标网站连通性...")
    if not fetcher.ping():
        print("[!] 连通性测试失败，请检查网络环境或目标网站状态。")
        return
    print("[+] 连通性测试通过！\n")

    # 执行抓取
    try:
        articles = fetcher.fetch(since=since_date)
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
        
        # 截取前 60 个字符作为正文预览，去掉换行符保持整洁
        content_preview = art.content[:60].replace('\n', ' ') + "..." if art.content else "（无正文）"
        print(f"     📄 正文: {content_preview}")
        
        if art.img_urls:
            print(f"     🖼️ 图片: 包含 {len(art.img_urls)} 张图")
            # 打印第一张图片链接作为抽查
            print(f"             首图 -> {art.img_urls[0]}")
        print("-" * 50)


if __name__ == "__main__":
    main()