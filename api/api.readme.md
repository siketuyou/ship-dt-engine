# Spider Service API 文档

## 概览

| 项目 | 值 |
|------|-----|
| 框架 | FastAPI |
| 默认端口 | `8000`（由 `SERVICE_PORT` 环境变量控制） |
| 启动命令 | `uvicorn api.main:app --host 0.0.0.0 --port 8000` |
| 交互文档 | `http://localhost:8000/docs` |

---

## 统一响应格式

所有接口（除文件下载外）均返回以下结构：

```json
{
  "code": 200,
  "message": "success",
  "data": {}
}
```

| 字段 | 说明 |
|------|------|
| `code` | `200` 成功，`400` 参数错误，`409` 冲突，`500` 服务端错误 |
| `message` | 描述信息 |
| `data` | 业务数据，失败时为 `null` |

---

## 健康检查

### `GET /health`

服务存活探针，供 Consul / 负载均衡器调用。

**响应**

```json
{ "status": "ok" }
```

---

## 采集器

### `GET /api/fetcher/list`

列出 `fetchers/` 目录下已部署的采集器模块名。

**响应**

```json
{
  "code": 200,
  "message": "success",
  "data": ["csic", "gov_policy"]
}
```

---

## 模型管理

模型（`reptile_model`）是爬虫任务的配置单元，包含目标站点、采集器、Cron 表达式和关键词列表。

---

### `GET /api/model/list`

分页查询模型列表。

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `pageNum` | int | `1` | 页码，≥1 |
| `pageSize` | int | `10` | 每页条数，1–100 |

**响应 `data`**

```json
{
  "total": 5,
  "records": [
    {
      "mReptileModelId": 1,
      "mReptileModelName": "中船集团采集",
      "mReptileModelIntroduce": "采集中船官网公告",
      "mReptileModelWeb": "http://www.cssc.net.cn",
      "mReptileModelState": "stopped",
      "mReptileModelTime": "2025-01-10 09:00:00"
    }
  ]
}
```

`mReptileModelState` 取值：`stopped` / `running` / `error`

---

### `GET /api/model/{model_id}`

查询单个模型详情，含关键词列表。

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `model_id` | int | 模型 ID |

**响应 `data`**

```json
{
  "mReptileModelId": 1,
  "mReptileModelName": "中船集团采集",
  "mReptileModelIntroduce": "采集中船官网公告",
  "mReptileModelWeb": "http://www.cssc.net.cn",
  "mReptileModelState": "stopped",
  "mReptileModelTime": "2025-01-10 09:00:00",
  "mReptileModelScriptAddress": "csic",
  "cronExpression": "0 0 2 * * ?",
  "keywords": [
    {
      "keywordId": 3,
      "keywordName": "船舶",
      "useFlag": 1,
      "incrementalSpiderTime": "2025-03-01 00:00:00"
    }
  ]
}
```

---

### `POST /api/model/save`

创建或更新模型。`Content-Type: multipart/form-data`。

有 `mReptileModelId` 且数据库中存在时为更新，否则为新建。

**Form 字段**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `mReptileModelId` | string | 否 | 更新时传入模型 ID |
| `mReptileModelName` | string | 是 | 模型名称 |
| `mReptileModelIntroduce` | string | 否 | 简介，默认空 |
| `mReptileModelWeb` | string | 是 | 目标站点 URL |
| `fetcherName` | string | 否 | 采集器模块名（不含 `_fetcher` 后缀） |
| `cronExpression` | string | 否 | Cron 表达式，支持 5 位或 6 位（含秒） |
| `keywords` | string | 否 | JSON 数组，见下方格式，默认 `[]` |
| `scriptFile` | file | 否 | 上传新采集器 `.py` 文件，上传时 `fetcherName` 必填 |

**`keywords` JSON 格式**

```json
[
  { "keywordName": "船舶", "useFlag": 1 },
  { "keywordId": 3, "keywordName": "军舰", "useFlag": 1, "incrementalSpiderTime": "2025-01-01 00:00:00" }
]
```

- 有 `keywordId` 时更新该条；无时新增。
- 未出现在列表中的已有关键词会被软删除。

**响应 `data`**

```json
{ "mReptileModelId": 1 }
```

**采集器上传规则**

上传的 `.py` 文件会经过以下校验后才写库：
1. 语法编译通过（`py_compile`）
2. 能成功 import
3. 存在名为 `{FetcherName}Fetcher` 的类且继承 `BaseFetcher`

校验失败返回 `code: 400`，数据库不变。

---

### `DELETE /api/model/{model_id}`

软删除模型（`deleted=1`）。

**响应**

```json
{ "code": 200, "message": "删除成功", "data": null }
```

---

### `POST /api/model/{model_id}/start`

手动触发模型采集，异步后台执行。

- 同一模型已在运行时返回 `code: 409`。
- 执行完成后自动写入运行日志（`reptile_model_log`）。

**响应**

```json
{ "code": 200, "message": "启动成功", "data": null }
```

---

### `POST /api/model/{model_id}/stop`

标记模型状态为 `stopped`，释放运行锁。

> 注：当前为标记操作，不会强制中断已在运行的线程。

**响应**

```json
{ "code": 200, "message": "停止成功", "data": null }
```

---

## 关键词管理

关键词（`keyword`）属于某个模型，控制增量采集的起始时间和启用状态。

---

### `GET /api/model/{model_id}/keywords`

查询模型下所有有效关键词。

**响应 `data`**

```json
[
  {
    "keywordId": 3,
    "keywordName": "船舶",
    "useFlag": 1,
    "incrementalSpiderTime": "2025-03-01 00:00:00"
  }
]
```

---

### `POST /api/model/keyword`

为模型新增单个关键词。`Content-Type: application/json`。

**请求体**

```json
{
  "modelId": 1,
  "keywordName": "军舰",
  "useFlag": 1
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `modelId` | int | 是 | 所属模型 ID |
| `keywordName` | string | 是 | 关键词文本 |
| `useFlag` | int | 否 | `1` 启用，`0` 禁用，默认 `1` |

**响应 `data`**

```json
{ "keywordId": 8 }
```

---

### `DELETE /api/model/keyword/{keyword_id}`

软删除单个关键词。

**响应**

```json
{ "code": 200, "message": "删除成功", "data": null }
```

---

## 运行日志

### `GET /api/model/logs`

分页查询模型的历史运行记录。

**Query 参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `modelId` | int | 是 | 模型 ID |
| `state` | string | 否 | 筛选状态：`stopped` / `running` / `error` |
| `pageNum` | int | 否 | 默认 `1` |
| `pageSize` | int | 否 | 默认 `10`，最大 `100` |

**响应 `data`**

```json
{
  "total": 12,
  "records": [
    {
      "logId": 42,
      "runTime": "2025-04-01 02:00:05",
      "runState": "stopped",
      "resultDesc": "采集完成，共 128 条",
      "csvAddress": "data/output/model_1_20250401.csv",
      "entryState": "done",
      "entryTime": "2025-04-01 02:05:10"
    }
  ]
}
```

---

### `DELETE /api/model/{model_id}/logs`

软删除模型的所有运行日志。

**响应**

```json
{ "code": 200, "message": "清空成功", "data": null }
```

---

## CSV 操作

### `POST /api/model/import-csv`

将 CSV 文件中的数据导入到数据库入库记录，关联到指定运行日志。`Content-Type: multipart/form-data`。

**Form 字段**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | 是 | CSV 文件 |
| `logId` | int | 是 | 关联的运行日志 ID |
| `userId` | int | 否 | 操作用户 ID，默认 `0` |

**响应 `data`**

由 `CsvImporter` 返回的导入结果统计对象。

---

### `GET /api/model/download-csv`

下载指定路径的 CSV 文件。

**Query 参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `filePath` | string | 是 | 服务器上的文件绝对/相对路径 |

文件不存在时返回 HTTP `404`。响应 `Content-Type` 为 `text/csv`。

---

## Cron 定时任务

在 `POST /api/model/save` 时若传入 `cronExpression`，服务会自动注册/更新 APScheduler 定时任务。

**表达式格式**

| 格式 | 示例 | 说明 |
|------|------|------|
| 5 位（标准） | `0 2 * * *` | 每天凌晨 2:00 |
| 6 位（含秒） | `0 0 2 * * ?` | 每天凌晨 2:00:00 |

同一模型重复保存会覆盖已有定时任务；`cronExpression` 为空则不注册。

---

## 错误码速查

| code | 场景 |
|------|------|
| `200` | 成功 |
| `400` | 参数缺失 / 采集器校验失败 |
| `404` | 模型或文件不存在（HTTP 404） |
| `409` | 模型已在运行中，不可重复启动 |
| `500` | 数据库操作失败 / 未知服务端错误 |
