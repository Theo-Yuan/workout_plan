#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

TODAY=$(date +%Y-%m-%d)

# 获取 agent 决策所需的原始数据（官方计划 + 最近实际训练 + profile 摘要）
PLAN_JSON=$(python3 .agents/sched/workout_preview.py --plan 2>/dev/null)
if [ -z "$PLAN_JSON" ]; then
    echo "FATAL: Cannot get plan data" >&2
    exit 1
fi

WEEKDAY=$(printf '%s' "$PLAN_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['weekday'])")

# 提取官方计划（今天及未来几天的训练日/休息日）
PLAN_LINES=$(printf '%s' "$PLAN_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
today = data['date']
for d in data['official_plan']:
    if d['datestr'] >= today:
        status = '训练' if d['day_type']=='training' else '休息'
        name = d.get('workout_name') or '-'
        print(f\"  {d['datestr']}  {status}  {name}\")
")

# 提取最近实际训练
RECENT_LINES=$(printf '%s' "$PLAN_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for r in data['recent_trainings']:
    print(f\"  {r['datestr']}  {r['title']}  {r['duration_min']}min\")
")

# 提取漏练检测（计划安排了但实际未执行的训练日）
MISSED_LINES=$(printf '%s' "$PLAN_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
missed = data.get('missed_sessions', [])
if not missed:
    print('  （无漏练）')
for m in missed:
    name = m.get('workout_name') or '-'
    print(f\"  {m['datestr']}  未执行  {name}\")
")

PROMPT_FILE=$(mktemp /tmp/workout-prompt-$$-XXXXXX.txt)
trap "rm -f $PROMPT_FILE" EXIT

cat > "$PROMPT_FILE" <<'PROMPT_EOF'
你是训记训练助手。请根据以下数据，自主判断今天该预告什么训练，生成预告并发送到 Discord。

## 今日
- 日期: TODAY_PLACEHOLDER (WEEKDAY_PLACEHOLDER)

## 训记官方计划（日期→训练日/休息日的真实映射，仅供参考）
PLAN_PLACEHOLDER

## 最近实际训练记录（实际执行的训练，判断进度的依据）
RECENT_PLACEHOLDER

## 漏练检测（官方计划安排了训练日，但实际未执行的）
MISSED_PLACEHOLDER

## 你的任务
1. 读取 .agents/profile.md 了解用户偏好、限制、当前阶段（减载周等）
2. 综合判断今天该预告什么训练：
   - **先处理漏练**：若 missed_sessions 存在漏练的训练日，应优先考虑补练
     （把漏练的分化类型补到今天/最近可练日），而不是直接按原计划推进
   - **以最近实际训练进度为准**：看最近一次实际训练是什么阶段（推/拉/腿），按 PPL 循环（推→拉→腿）取下一个作为今天阶段
   - 官方计划仅作参考：若官方计划今天标注了训练日，可作为交叉验证；但用户实际可能休息/加练/调整，不要假设严格按计划执行
   - 结合 profile 的偏好（如腿部打磨期小重量）、减载周状态、身体疲劳等
3. 确定今天的阶段后，从知识库/计划设计中选择该阶段的动作（或参考官方计划该日的动作）
4. 生成 Discord 消息并发送到 target="学习星球/健身打卡"
5. 发送完成后输出 Done

## 消息格式（严格遵循）
- 用中文，简洁有力
- 动作列表格式：编号. 动作名 × 组数 × 次数范围 @ 重量建议
- 结合 profile 和近期数据给出个性化 💡 提示
- 消息不超过 800 字符

示例格式：
🏋️ **今日训练预告 — 推日**
📅 2026-07-28（周二）| 🎯 渐进增肌

1. 杠铃卧推  × 4组 × 6-10次 @ 60-90kg
2. 器械坐姿推举  × 4组 × 10-12次 @ 40kg
3. 绳索侧平举（单边）  × 3组 × 12-15次
4. 绳索臂屈伸  × 3组 × 10-15次

💡 卧推先做，力竭前保留 1-2 rep；辅助动作控制离心。

## 约束
- 阶段判断以实际进度为准，官方计划作参考
- 减载周务必提醒「组数减半、不要力竭」
- 若今天是休息日（官方计划 rest 且实际也无训练），可预告「今日休息」或建议恢复性活动
- 发送完成后必须输出 Done（只输出一次）
PROMPT_EOF

sed -i '' \
    -e "s/TODAY_PLACEHOLDER/$TODAY/g" \
    -e "s/WEEKDAY_PLACEHOLDER/$WEEKDAY/g" \
    "$PROMPT_FILE"

# 替换 PLAN/RECENT/MISSED 占位符（多行）
TMP_PROMPT2=$(mktemp /tmp/workout-prompt2-$$-XXXXXX.txt)
while IFS= read -r line; do
    if [[ "$line" == "PLAN_PLACEHOLDER" ]]; then
        echo "$PLAN_LINES" >> "$TMP_PROMPT2"
    elif [[ "$line" == "RECENT_PLACEHOLDER" ]]; then
        echo "$RECENT_LINES" >> "$TMP_PROMPT2"
    elif [[ "$line" == "MISSED_PLACEHOLDER" ]]; then
        echo "$MISSED_LINES" >> "$TMP_PROMPT2"
    else
        echo "$line" >> "$TMP_PROMPT2"
    fi
done < "$PROMPT_FILE"
mv "$TMP_PROMPT2" "$PROMPT_FILE"

MAX_ATTEMPTS=3
TIMEOUT_SEC=90
RETRY_DELAY=10

for attempt in $(seq 1 $MAX_ATTEMPTS); do
    echo "[$(date '+%H:%M:%S')] Attempt $attempt/$MAX_ATTEMPTS: launching opencode..." >&2

    opencode run \
        --pure \
        --auto \
        --dir "$PROJECT_DIR" \
        --title "训练预告 $TODAY" \
        "$(cat "$PROMPT_FILE")" &
    OP_PID=$!

    elapsed=0
    while [ $elapsed -lt $TIMEOUT_SEC ]; do
        if ! kill -0 $OP_PID 2>/dev/null; then
            wait $OP_PID
            EXIT_CODE=$?
            if [ $EXIT_CODE -eq 0 ]; then
                echo "[$(date '+%H:%M:%S')] ✓ opencode success (attempt $attempt)" >&2
                exit 0
            fi
            echo "[$(date '+%H:%M:%S')] ✗ opencode exit=$EXIT_CODE (attempt $attempt)" >&2
            break
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    if kill -0 $OP_PID 2>/dev/null; then
        echo "[$(date '+%H:%M:%S')] ✗ opencode timeout after ${TIMEOUT_SEC}s (attempt $attempt)" >&2
        kill $OP_PID 2>/dev/null
        wait $OP_PID 2>/dev/null || true
    fi

    if [ $attempt -lt $MAX_ATTEMPTS ]; then
        echo "[$(date '+%H:%M:%S')] Retrying in ${RETRY_DELAY}s..." >&2
        sleep $RETRY_DELAY
    fi
done

echo "[$(date '+%H:%M:%S')] FATAL: All $MAX_ATTEMPTS attempts failed" >&2
exit 1
