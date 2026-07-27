---
description: "训记训练数据 Open API —— 读取/写回训练记录、RPE、官方计划"
---

# 训记训练数据 Open API Skill

## 原则
- 本地数据优先：过去日期的查询走 `query_train.py`（cache-through），自动处理本地→API→回写缓存。
- 本 Skill 仅定义 API 交互规则。CRUD 操作由以下 CLI 脚本封装（Agent 直接调用即可）：
  - `python .agents/db/query_train.py --date YYYY-MM-DD` — 读（cache-through，防缓存穿透）
  - `python .agents/db/write_train.py --dry-run < data.json` — 写前验证
  - `python .agents/db/write_train.py --confirmed < data.json` — 确认写入 + 自动同步缓存
  - `python .agents/db/sync_train.py --months N` — 批量历史同步
- 分析是判断密集型工作，不由脚本硬编码。Agent 直接在本地 SQLite 上做查询推理：
  - `sqlite3 .agents/db/train.db "SELECT ..."` 或
  - 写临时 Python 脚本执行复杂查询
- 写回前必须先展示变更摘要，并等待用户确认。

@_shared/auth.md

@_shared/auth.train.md

> **训练知识库**: 另见 `knowledge/00-快速导航.md`（Agent 需用 Read 工具加载）
> **用户画像**: 另见 `.agents/profile.md`（Agent 需用 Read 工具单独加载）

## 本地数据库（SQLite）

路径：`.agents/db/train.db`

```sql
-- 同步元数据（记录哪些日期已同步/标记为空）
sync_meta(key TEXT PK, value TEXT)
  -- key = "synced_{datestr}", value = "1"

-- 训练主表
trains(localid INTEGER PK, datestr TEXT, title TEXT,
       start_ms INTEGER, end_ms INTEGER, duration_s INTEGER,
       note TEXT)

-- 动作
movements(id INTEGER PK AUTO, train_id INTEGER → trains.localid,
          name TEXT, idx INTEGER, difficulty TEXT)

-- 组
sets(id INTEGER PK AUTO, movement_id INTEGER → movements.id,
     idx INTEGER, done INTEGER, weight_kg REAL, reps INTEGER,
     rpe TEXT, time_s INTEGER, self_weight INTEGER)
```

Agent 执行分析时用 `sqlite3` 直接查询：

```bash
sqlite3 .agents/db/train.db "SELECT ..."
```

或编写临时 Python 脚本做复杂联结查询。

## 接口
- 训练记录 Base URL: `https://trains.xunjiapp.cn`
- 读取训练: `POST /api_trains_for_llm_v2`
- 写回训练: `POST /api_upsert_trains_for_llm_v2`
- 官方计划 Base URL: `https://api.xunjiapp.cn`
- 读取官方计划: `POST /open/plan/query_gzip`
- 成功时核心数据在 `res`；不要要求返回里必须有 `success === true`。
- 标准动作中文名: `https://github.com/Foveluy/Xunji-movements`

## 读取
```http
POST https://trains.xunjiapp.cn/api_trains_for_llm_v2
Authorization: Bearer {{XUNJI_TRAIN_API_KEY}}
Content-Type: application/json

{
  "schema_version": "train_open_api_v2",
  "datestr": "2026-04-02",
  "include_full_data": false
}
```

- 默认 `include_full_data: false`，只返回适合普通读取的轻量数据。
- 需要未打勾组、RPE、备注、完成感受、左右侧重量、实练秒数或每组休息秒数时，传 `include_full_data: true`。
- 有氧、计时、Tabata、苹果健康等记录型动作会在 `sets[].metrics` 返回 distance/kcal/calories/workoutTime/avgHeartRate/maxHeartRate/minHeartRate 等摘要指标。
- 获取心率数据时，必须用 `include_full_data: true` 读取。普通训练 note 里的整次训练心率在 `trains[].heartRate`；有氧/苹果健康等动作级心率摘要在 `sets[].metrics.avgHeartRate/maxHeartRate/minHeartRate`，压缩趋势在 `sets[].heartRate`。
- `sets[].heartRate` 字段包含 `avg/max/min/duration/count/step/values/peak`；`values` 最多 50 个分桶平均 BPM 点，第 N 个点的时间约为 `N * step` 秒。接口永远不返回原始心率数组。
- 如果训练没有 `trains[].heartRate`，各组也没有心率摘要或 `heartRate`，说明这次训练没有可导出的心率数据；不要因为缺少 `heartRates` 原始数组就判断失败。
- 苹果健康训练的 `name` 返回运动类型，例如 `Running`；老数据会尽量从训练标题推断。
- 超级组/递减组会在 `sets[].items[]` 返回子动作；每个子项的 `set` 里有 weight/unit/reps/time/metrics。
- 返回里的训练在 `res.trains`；写回旧训练时保留 `localid`、`start`、`end`。
- 动作不会暴露内部 key；需要标准动作名时读取 GitHub 动作名表。

## 读取官方计划
- ⛔ **官方计划仅支持读取，不支持修改/写入。** 接口使用本 Skill 中同一个训练数据 Key；调用前用户必须先在 App 申请 Key。
- ⛔ **如果用户请求编辑计划（修改动作、更换组次、增删休息日等），应明确告知此限制：**
  > 训记 Open API 不支持修改计划。计划编辑需在训记 App 中手动操作。
  >
  > 替代能力：可提供计划分析建议（容量评估、动作合理性、渐进策略等），或写回训练历史记录作为实际完成数据。
- 接口返回 gzip 压缩 JSON（`Content-Encoding: gzip`）。大多数 HTTP 客户端会自动解压；不会自动解压时，先解 gzip 再解析 JSON。
- 先列出计划，再使用返回的 `plan_ref` 查询日期范围。`platform:155` 和 `universal:155` 表示两个不同的计划实例。
```http
POST https://api.xunjiapp.cn/open/plan/query_gzip
Authorization: Bearer {{XUNJI_TRAIN_API_KEY}}
Accept-Encoding: gzip
Content-Type: application/json

{
  "schema_version": "plan_open_api_v1",
  "action": "list"
}
```
```json
{
  "schema_version": "plan_open_api_v1",
  "action": "get",
  "plan_ref": "platform:155",
  "start_date": "2026-07-12",
  "end_date": "2026-08-12",
  "include_movements": true
}
```
- `list` 在 `res.plans` 返回计划摘要；`get` 返回 `res.plan`、`res.date_range` 和 `res.days`。
- `get` 不传日期时默认读取今天前 7 天到后 30 天；自定义日期范围最多 92 天。
- 只需要日历时传 `include_movements: false`。动作会返回中文名和目标组，不返回内部动作 key、rules 或同步元数据。

## 写回
```http
POST https://trains.xunjiapp.cn/api_upsert_trains_for_llm_v2
Authorization: Bearer {{XUNJI_TRAIN_API_KEY}}
Content-Type: application/json

{
  "schema_version": "train_open_api_v2",
  "client_request_id": "unique-id-from-agent",
  "dry_run": false,
  "include_full_data": false,
  "res": [
    {
      "datestr": "2026-04-02",
      "localid": 123456,
      "title": "胸部训练",
      "start": 1744010000000,
      "end": 1744013600000,
      "movements": [
        { "name": "杠铃卧推", "sets": [
          { "done": true, "weight": "60", "unit": "kg", "reps": "10" }
        ] }
      ]
    }
  ]
}
```

## RPE 与动作完成难度
- 改 RPE 或动作完成难度前，用 `include_full_data: true` 读取原训练；写回时保留原训练其它动作、组和 note 元数据。
- RPE 写在具体组上：`movements[].sets[].rpe`。合法值用字符串：`"6"`、`"6.5"`、`"7"`、`"7.5"`、`"8"`、`"8.5"`、`"9"`、`"9.5"`、`"10"`；清空 RPE 用 `""`，不要写 `0`。
- 超级组/递减组子项的 RPE 写在对应子项的 `sets[].items[].set.rpe`。
- 简单/正常/困难写在动作对象上：`movements[].difficulty`，合法值只用 `easy`、`normal`、`hard`；不要把中文“简单/正常/困难”写进字段。
- 写回涉及 RPE 或 `difficulty` 时，建议请求里传 `include_full_data: true`，方便服务端返回完整标准化数据。
```json
{
  "include_full_data": true,
  "res": [
    {
      "datestr": "2026-04-02",
      "localid": 123456,
      "movements": [
        {
          "name": "杠铃卧推",
          "difficulty": "hard",
          "sets": [
            { "done": true, "weight": "60", "unit": "kg", "reps": "10", "rpe": "8.5" }
          ]
        }
      ]
    }
  ]
}
```

## 历史颜色
- 训练历史卡片颜色存在训练 `note.trainColor`，不是顶层 `color`。
- 改颜色前先读取原训练；写回时保留 `localid`、`datestr`、`start`、`end`、`title`、`movements` 和 `note` 里的其它元数据，只改 `trainColor`。
- 颜色使用 CSS 十六进制字符串，如 `#FF7A00`；清空自定义历史颜色用 `""`。
- 如果 `note` 是 JSON 字符串，先解析成对象，合并 `trainColor` 后再按接口支持的形态写回 `note`；不要覆盖 `text`、`heartRate`、`customTitle`、`personalworkout_*` 等字段。
```json
{
  "localid": 123456,
  "datestr": "2026-04-02",
  "note": {
    "text": "今天状态不错",
    "trainColor": "#FF7A00"
  }
}
```

## 写回规则
- 写回动作只传中文 `name`，不要传 `key`；服务端会按中文名查找并回填内部 key。
- 不确定中文名时，先读取 `https://github.com/Foveluy/Xunji-movements`，只从表里的中文名里选择。
- `res` 可以是训练数组，也可以是 `{ "trains": [...] }`；单次最多 4 条训练，且必须属于同一天。
- 每条训练最多 15 个动作；每个动作最多 20 组，超过会被服务端拒绝。
- 有 `localid` 时更新原训练；没有 `localid` 时新建训练；不要因为列表里缺少旧训练就删除旧训练。
- 更新旧训练时保留 `localid`、`start`、`end`，除非用户明确要改时间。
- 组至少包含 `weight`/`weight_kg`、`reps`、`time`/`duration_s`、`selfWeight` 之一。
- 未完成组用 `done: false`；不要把完整模式读到的未完成组擅自删掉。
- **写回时 `done: false` 的组会被 API 丢弃**——写回仅保留已打勾（`done: true`）的组。如需预创建未来训练模板，每个动作至少保留 1 组 `done: true` 作为占位。
- 写回成功后，用服务端返回的标准化 `res` 覆盖缓存。
- **成功响应可能无 `success` 字段**——API 有时只返回 `res.trains` 数据而无顶层 `success`。判断写回成功应检查 `res.trains` 是否存在数据，而非仅依赖 `success` 字段。
- **限频响应有两种格式**——`{"__rate_limited__": true}` 或 `{"success": false, "error": "too frequent, retry after 32s"}`，两种都需要处理。

## 限频与错误

@_shared/error-handling.md

### 训练数据特有
- 同一用户同一训练日：默认读取 15 秒一次，`include_full_data: true` 读取 30 秒一次，写回 45 秒一次。
- 官方计划的 `list`/`get` 按同一 Key、操作和计划实例 15 秒限频；重试前等待 `retry_after_ms`。
- 不确定动作名时不要编造；让用户确认中文动作名后再写回。
