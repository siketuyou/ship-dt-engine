# 项目：数字化转型信息数据库 - Python 爬虫引擎

## 架构概述
本项目采用 11 层单向依赖架构，层间通过 Pydantic 模型传递数据，禁止跨层 import。

## 分层结构
- L0 main.py：唯一入口，仅做 CLI 路由
- L1 config/settings.py：pydantic-settings 全局配置单例
- L2 models/schemas.py：RawArticle / CleanedItem / EnrichedItem 三个 Pydantic 模型
- L3 storage/state_store.py：增量时间戳持久化
- L4 utils/：logger.py（日志工厂）+ http_client.py（限速 HTTP）
- L5 ai/：llm_client.py + prompt_manager.py + result_parser.py（Ollama/DeepSeek）
- L6 fetchers/：base_fetcher.py 抽象基类 + 各站点采集器
- L7 processor/：filter_engine → dedup_engine → cleaner → extractor → geo_encoder
- L8 exporters/：csv_writer + media_downloader + java_api_client
- L9 orchestrator/pipeline.py：全流程编排器，唯一知晓各层的协调者
- L10 scheduler/task_runner.py：APScheduler Cron 守护进程

## 强制编码规范
- 日志：必须 get_logger(__name__)，禁止 print()
- HTTP：必须使用 RateLimitedClient，禁止直接 requests.get()
- 层间数据：必须传 Pydantic 模型，禁止裸 dict
- 配置：必须从 settings 读取，禁止硬编码 URL/密钥/超时
- fetch() 内单条失败必须降级（记录警告跳过），不得抛异常终止整批

## 数据流
RawArticle → (filter) → RawArticle → (clean) → CleanedItem → (dedup) →
CleanedItem → (extract) → EnrichedItem → (geo) → EnrichedItem → CSV → Java API

## 技术栈
Python 3.11, pydantic v2, pydantic-settings, requests, beautifulsoup4,
scikit-learn, ollama(local), apscheduler, pytest
```

---