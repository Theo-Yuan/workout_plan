#!/usr/bin/env python3
"""Generate Discord workout summary from today's train data."""
import json
import subprocess
import sys
from datetime import date

DISCORD_PYTHON = "/Users/theoyuan/.local/share/discord-mcp/venv/bin/python"

TODAY = date.today().isoformat()
TARGET = "学习星球/健身打卡"


def query_today() -> list:
    result = subprocess.run(
        ["python3", ".agents/db/query_train.py", "--date", TODAY, "--json"],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)


def generate_summary(data: list) -> str:
    trains = data[0]["trains"]
    train = trains[-1]
    title = train["title"]
    movements = train["movements"]

    total_sets = 0
    total_reps = 0
    move_lines = []

    for m in movements:
        name = m["name"]
        sets = m["sets"]
        for s in sets:
            w = s.get("weight_kg")
            if w is not None:
                weight_str = f"{int(w)}kg" if w == int(w) else f"{w}kg"
            else:
                weight_str = "自重"
            move_lines.append(
                f"{name}     {len(sets)}x{s['reps']} @ {weight_str}"
            )
            total_sets += len(sets)
            total_reps += s["reps"]

    if "腿" in title:
        day_type = "腿"
    elif "推" in title:
        day_type = "推"
    elif "拉" in title:
        day_type = "拉"
    else:
        day_type = title

    lines = [
        f"✅ **今日训练完成 — {day_type}日**",
        "",
        f"📅 {TODAY} | 🎯 {title}",
        "",
        "```",
        *move_lines,
        "```",
        "",
        f"📊 总计：{total_sets} 组 · {total_reps} 次",
        "",
        f"💪 坚持就是胜利！ #{day_type}日",
    ]
    return "\n".join(lines)


def send_discord(message: str, target: str = TARGET):
    result = subprocess.run(
        [DISCORD_PYTHON, ".agents/sched/send_discord.py", target],
        input=message, capture_output=True, text=True
    )
    print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    return result.returncode == 0


def main():
    data = query_today()
    if not data:
        print(f"No training data for {TODAY}")
        return

    summary = generate_summary(data)
    print(summary)
    print()

    if send_discord(summary):
        print("Sent to Discord")
    else:
        print("Failed to send to Discord", file=sys.stderr)


if __name__ == "__main__":
    main()
