#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

TODAY=$(date +%Y-%m-%d)
WEEKDAY=$(date +%A)

PROMPT_FILE=$(mktemp /tmp/workout-prompt-$$-XXXXXX.txt)
trap "rm -f $PROMPT_FILE" EXIT

cat > "$PROMPT_FILE" <<'PROMPT_EOF'
你是训记训练助手。根据计划为今天生成训练预告，发送到 Discord。

今日：TODAY_PLACEHOLDER（WEEKDAY_PLACEHOLDER）

## 你的任务
1. 读取 .agents/profile.md — 获取用户偏好、限制、当前阶段
2. 读取 knowledge/计划设计.md — 获取动作模板
3. 根据计划（腿推拉PPL循环）和当前阶段，生成今日训练计划
4. 用 discord_send_message 发送到 target='学习星球/健身打卡'

## 消息格式
🏋️ **今日训练预告 — {分化类型}日**
📅 {日期}（{星期}）| 🎯 {阶段目标}
```
{编号动作列表：动作名 × 组数×次数 @ 重量建议}
```
💡 {一句关键提醒}

## 约束
- 严格遵循 profile.md 中的偏好和限制（如不做杠铃深蹲、器械优先等）
- 消息不超过 800 字符
- 发送完毕后输出 Done
PROMPT_EOF

sed -i '' "s/TODAY_PLACEHOLDER/$TODAY/g; s/WEEKDAY_PLACEHOLDER/$WEEKDAY/g" "$PROMPT_FILE"

exec opencode run \
  --pure \
  --auto \
  --dir "$PROJECT_DIR" \
  --title "训练预告 $TODAY" \
  "$(cat "$PROMPT_FILE")"
