# Ship Digital Python — 船舶情报爬虫服务

## 项目概述

面向船舶行业的自动化情报采集与结构化提取系统。系统从目标网站（当前已接入中国船舶集团 CSIC）抓取新闻资讯，经关键词过滤、清洗去重后，交由本地大模型（Ollama / DeepSeek-R1）提取装备情报字段，最终输出 CSV 并可导入业务数据库。

---

## 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                     API 层 (FastAPI)                    │
│  api/main.py                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ 模型管理 API  │  │ 关键词管理    │  │ CSV 导入/下载│   │
│  └──────────────┘  └──────────────┘  └──────────────┘   │
│  ┌──────────────────────────────────────────────────┐   │
│  │  APScheduler (BackgroundScheduler)  Cron 定时触发 │   │
│  └──────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────┘
                         │ 调用
                         ▼
┌─────────────────────────────────────────────────────────┐
│              Orchestrator（流水线调度器）                │
│  orchestrator/orchestrator.py                           │
│                                                         │
│  Step 1  关键词校验（DB）                                 │
│  Step 2  load_fetcher → Fetcher（按 model_name 动态加载）│
│  Step 3  Filter   ──────────────────────────────────┐   │
│  Step 4  Cleaner  ──────────────────────────────────┤   │
│  Step 5  Dedup    ──────────────────────────────────┤   │
│  Step 6  Extractor ─────────────────────────────────┤   │
│  Step 7  CsvWriter ─────────────────────────────────┤   │
│  Step 8  CsvImporter（可选自动入库）─────────────────┘    │
│                                                         │
│  run() 返回 (ok, result_desc, csv_path) 三元组           │
└─────────────────────────────────────────────────────────┘
```

---

## 流水线各步骤详解

### Step 2 — Fetcher（采集层）

| 文件 | 说明 |
|------|------|
| `fetchers/base_fetcher.py` | 抽象基类，定义 `fetch_all()` 接口，读取 DB 水位线 |
| `fetchers/load_fetcher.py` | **Fetcher 工厂**：按 `model_name` 动态加载对应 Fetcher 类 |
| `fetchers/csic/csic_fetcher.py` | CSIC 实现，翻页采集列表页 + 详情页正文 |


- **可插拔架构**：Orchestrator 不再硬编码 Fetcher，根据数据库中的 `model_name` 自动加载 `fetchers/{model_name}/{model_name}_fetcher.py` 中的 `{Modelname}Fetcher` 类
- 加载失败抛出 `FetcherNotFoundError` / `FetcherLoadError`（见 `exception.py`）
- 采用增量水位线（`incremental_spider_time`）防止重复采集
- 支持多编码自动探测（UTF-8 / GBK / GB18030）
- 输出：`List[RawArticle]`

> 新增网站接入只需：在 `fetchers/<name>/` 下放 `<name>_fetcher.py`，类名 `<Name>Fetcher`，并在 `reptile_model` 表中将 `m_reptile_model_name` 设为 `<name>` 即可，无需改动 Orchestrator。

### Step 3 — Filter（关键词过滤）

| 文件 | 说明 |
|------|------|
| `processor/filter.py` | 关键词过滤：AC 自动机 + 语义向量兜底 |
| `processor/ac_engine.py` | AC 自动机精确匹配 + `SemanticMatcher` 语义向量兜底 |

- **关 A**：AC 自动机精确/变体匹配（快）
- **关 B**：语义向量匹配兜底，阈值默认 0.65（慢，仅 AC 未命中时触发）
- 输出：`List[FilteredItem]`（含 `matched_keyword_ids`）

### Step 4 — Cleaner（清洗）

| 文件 | 说明 |
|------|------|
| `processor/cleaner.py` | 文本去噪：去除 HTML 标签、空白、特殊字符 |

- 输出：`List[CleanedItem]`

### Step 5 — Dedup（去重）

| 文件 | 说明 |
|------|------|
| `processor/dedup_engine.py` | SHA256(url) 指纹去重 |

- 输出：`List[CleanedItem]`（去重后）

### Step 6 — Extractor（LLM 结构化提取）

| 文件 | 说明 |
|------|------|
| `processor/extractor.py` | 调用 LLM，解析 JSON，组装 `EnrichedItem` |
| `ai/llm_client.py` | Ollama `/api/chat` 封装，支持 DeepSeek-R1 `<think>` 剥离 |
| `ai/prompts.py` | System prompt / User prompt 构建 |
| `ai/dimension_loader.py` | 从 DB 加载装备维度树（一级/二级/三级分类） |

**提取字段**：装备名称、服役年份、价格、使用单位、国家、地理坐标、三级维度分类、关键词摘要等

- 调用高德地图 API 将地名转换为经纬度
- LLM 输出的 `dim3_id` 会与维度树校验，非法值自动清空
- 最多重试 3 次
- 输出：`List[EnrichedItem]`

### Step 7 — CsvWriter（输出）

| 文件 | 说明 |
|------|------|
| `storage/csv_writer.py` | 写带摘要块的 CSV（UTF-8 BOM） |

输出文件名格式：`data/output/model_{id}_{timestamp}.csv`

摘要块包含：抓取总数 / 过滤后数 / 送入 LLM 数 / 提取成功数 / 成功率

### Step 8 — CsvImporter（可选入库）

| 文件 | 说明 |
|------|------|
| `storage/csv_importer.py` | 读取 CSV，逐行写入业务 DB |

可通过 `Orchestrator(auto_import=True)` 自动触发，也可通过 API 手动上传导入。

---

## 目录结构

```
ship_digital_python/
├── api/
│   └── main.py              # FastAPI 入口，REST 接口 + APScheduler（全局 DB 单例）
├── orchestrator/
│   └── orchestrator.py      # 流水线调度器，run() 返回 (ok, msg, csv_path)
├── exception.py             # 自定义异常体系（FetcherNotFound/Load/FetchError）
├── fetchers/
│   ├── base_fetcher.py      # 采集器抽象基类
│   ├── load_fetcher.py      # Fetcher 工厂（按 model_name 动态加载）
│   └── csic/
│       ├── csic_fetcher.py  # CSIC 采集实现
│       └── csic_config.py   # 栏目配置
├── processor/
│   ├── filter.py            # 关键词过滤（AC + 语义）
│   ├── ac_engine.py         # AC 自动机 + 语义向量匹配
│   ├── cleaner.py           # 文本清洗
│   ├── dedup_engine.py      # URL 指纹去重
│   └── extractor.py         # LLM 结构化提取
├── ai/
│   ├── llm_client.py        # Ollama 客户端（DeepSeek-R1）
│   ├── prompts.py           # Prompt 构建
│   └── dimension_loader.py  # 维度树加载
├── storage/
│   ├── db_manager.py        # SQLAlchemy 数据库访问层（含 raw_conn() 上下文管理器）
│   ├── csv_writer.py        # CSV 输出
│   └── csv_importer.py      # CSV 批量入库
├── models/
│   └── schemas.py           # Pydantic 数据模型
├── utils/
│   ├── logger.py            # 统一日志
│   ├── geo_encoder.py       # 高德地图地理编码
│   └── http_client.py       # HTTP 工具
├── scheduler/
│   └── scheduler.py         # 独立定时调度器（可替代 API 内置）
├── config/
│   └── settings.py          # 全局配置（pydantic-settings）
└── data/
    └── output/              # CSV 输出目录
```

---

## 数据模型流转

```
RawArticle          ← Fetcher 输出（按 model_name 动态加载）
    │
    ▼ Filter（AC + 语义匹配）
FilteredItem        ← 含 matched_keyword_ids
    │
    ▼ Cleaner
CleanedItem         ← 清洗后标准字段
    │
    ▼ Dedup（SHA256 去重）
CleanedItem（去重）
    │
    ▼ Extractor（LLM + 地理编码）
EnrichedItem        ← 完整装备情报记录
    │
    ▼ CsvWriter / CsvImporter
CSV 文件 / MySQL
```

---

## API 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/model/list` | 分页查询爬虫模型列表 |
| GET | `/api/model/{id}` | 查询模型详情（含关键词） |
| POST | `/api/model/save` | 新增/编辑模型（FormData + 文件上传） |
| DELETE | `/api/model/{id}` | 逻辑删除模型 |
| POST | `/api/model/{id}/start` | 手动触发流水线（后台线程） |
| POST | `/api/model/{id}/stop` | 停止运行中的模型 |
| GET | `/api/model/logs` | 查询运行日志 |
| DELETE | `/api/model/{id}/logs` | 清空运行日志 |
| GET | `/api/model/{id}/keywords` | 查询关键词列表 |
| POST | `/api/model/keyword` | 新增关键词 |
| DELETE | `/api/model/keyword/{id}` | 删除关键词 |
| POST | `/api/model/import-csv` | 手动上传 CSV 入库 |
| GET | `/api/model/download-csv` | 下载 CSV 文件 |

---

## 关键配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | 本地 Ollama 服务地址 |
| `DEFAULT_MODEL` | `deepseek-r1:8b` | LLM 模型 |
| `CSIC_BASE_URL` | `http://www.cssc.net.cn` | 中国船舶集团官网 |
| `DB_HOST` | `localhost:3306` | MySQL 数据库 |
| `DB_NAME` | `ship_digital_db` | 数据库名 |
| `DB_PASSWORD` | — | MySQL 密码（必填，从 `.env` 读取） |
| `REQUEST_DELAY` | `1.5s` | 礼貌延迟，防封禁 |

配置优先级：`.env` 文件 > 环境变量 > 代码默认值

> 现在 API/Scheduler/Orchestrator 统一通过 `settings.db_url` 拼装连接串，不再在源码中硬编码用户名/密码。

---

## 快速启动

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 API 服务
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 单次手动运行流水线（测试）
python orchestrator/orchestrator.py

# 独立定时调度器（可选）
python scheduler/scheduler.py
```

---

## 技术栈

| 层次 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| 定时调度 | APScheduler (CronTrigger) |
| 数据库 ORM | SQLAlchemy + PyMySQL |
| 爬虫 | Requests + BeautifulSoup4 (lxml) |
| 关键词匹配 | AC 自动机 + sentence-transformers 语义向量 |
| LLM 推理 | Ollama (DeepSeek-R1:8b) |
| 地理编码 | 高德地图 REST API |
| 数据模型 | Pydantic v2 |
| 配置管理 | pydantic-settings |
