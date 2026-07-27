---
description: "训记 Discord 通知 —— 训练预告 / 完成分享 / 分析推送到 Discord 频道"
---

# Discord 训练通知 Skill

## 前置条件

- Discord MCP Server 已配置（`opencode.json` 中有 `discord` MCP）
- Bot 已邀请到目标服务器并有 Send Messages 权限
- 目标频道：`学习星球/健身打卡`（ID: 1531141390208077895）

## 三种消息类型

### 1. 训练预告（今日计划）

**触发**：用户说"今天练什么"、"训练预告"、"帮我发个预告"

**数据来源**：读取 `query_train.py` 查最近训练确定分化周期 → 读取 `.agents/profile.md` 获取偏好 → 读取 `knowledge/计划设计.md` 获取动作模板

**消息格式**：

```
🏋️ **今日训练预告 — {分化类型}日**

📅 {日期}（{星期}）| 🎯 {阶段目标}

```
{编号动作列表：动作名 × 组数×次数范围 @ 重量建议}
```

💡 {一句关键提醒，基于当前阶段}
```

**动作填充规则**：
- 根据分化类型（推/拉/腿）从 `knowledge/计划设计.md` 的 PPL 模板选取
- 结合 `.agents/profile.md` 中的偏好和限制（如腿部打磨期不做杠铃深蹲）
- 参考近期训练数据给出重量建议（基于上次同动作表现）

### 2. 训练完成分享

**触发**：用户说"帮我发到 Discord"、"分享训练"、训练写入后主动推送

**数据来源**：`query_train.py --date {today} --json` 获取完整训练数据

**消息格式**：

```
✅ **训练完成** — {标题}

📅 {日期} | ⏱ {时长}

{动作摘要，每行：动作名 · {组数}×{次数} @{重量}}

📊 总容量：{总组数} 组 · {总次数} 次
{可选：vs 上次对比}
```

**容量计算**：
```sql
-- 从本地 SQLite 查询
SELECT m.name, COUNT(DISTINCT s.idx) as sets, SUM(s.reps) as reps, s.weight_kg
FROM movements m JOIN sets s ON s.movement_id = m.id
WHERE m.train_id = {localid} AND s.done = 1
GROUP BY m.name
```

**对比逻辑**（可选，用户要求时）：
- 查上一次同类分化训练，对比主要动作的重量/次数变化
- 简短标注：`📈 卧推 80kg×5 → 85kg×5` 或 `➡️ 持平`

### 3. 训练分析推送

**触发**：用户说"分析一下"、"看看最近状态"

**数据来源**：SQLite 复合查询 + 训练知识库

**消息格式**：

```
📈 **近期训练分析**

**{分化类型}**（近 {N} 次）
{主要动作}：{趋势描述}
容量趋势：{增加/减少/持平}

**关键发现**
• {发现1}
• {发现2}

**建议**
• {建议1}
```

## 发送方式

使用 Discord MCP 工具：

```
discord_send_message(
  target = "学习星球/健身打卡",
  message = {组装好的消息}
)
```

## 消息规范

- Discord 单条消息限 2000 字符，超长拆分为多条
- 用中文，保持简洁有力
- 用 emoji 分隔段落，提高可读性
- 不要包含 API Key、数据库路径等敏感信息
- 重量统一用 kg，时间用 分钟
- 消息末尾可加标签：`#腿日` `#推日` `#拉日`

## 频道信息

| 服务器 | 频道 | 用途 |
|--------|------|------|
| 学习星球 | #健身打卡 | 训练分享主频道 |
| 学习星球 | #✅学习打卡 | 学习打卡（非训练） |

---

## 脚本工具

项目内置了可直接调度或手动调用的脚本：

### workout_summary.sh / workout_summary.py

训练完成后，生成摘要并发送到 Discord。

```bash
# 生成今日训练摘要并发送到 Discord
./.agents/sched/workout_summary.sh
python3 .agents/sched/workout_summary.py
```

**数据来源**：`query_train.py --date {today} --json`

**自动识别分化类型**：从训练标题提取「推/拉/腿」。

### send_discord.py

底层发送工具，支持命令行调用。

```bash
echo "消息内容" | python3 .agents/sched/send_discord.py "学习星球/健身打卡"
```

**Token 来源**：macOS Keychain（`discord-bot-token` / `opencode`）

### workout_preview.sh

训练预告脚本（已有）。生成当日训练计划并发送到 Discord。

```bash
./.agents/sched/workout_preview.sh
```

### 调度建议

可将脚本加入 crontab 实现自动化：

```bash
# 每天早上 7:00 发送训练预告
0 7 * * * /path/to/.agents/sched/workout_preview.sh

# 每天晚上 22:00 检查并发送训练总结
0 22 * * * /path/to/.agents/sched/workout_summary.sh
``` |
