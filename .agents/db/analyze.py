#!/usr/bin/env python3
"""
训记训练数据分析

从本地 SQLite 读取训练数据，输出分析报告。
用法:
    python .agents/db/analyze.py                   # 完整报告
    python .agents/db/analyze.py --movement "杠铃卧推"  # 单个动作进展
"""

import argparse
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "train.db"


def get_conn():
    if not DB_PATH.exists():
        print(f"[错误] 数据库不存在: {DB_PATH}")
        print("       请先运行 sync_train.py 同步数据")
        exit(1)
    return sqlite3.connect(str(DB_PATH))


def report_overview(conn):
    """训练概览：总天数、频率、时长"""
    stats = conn.execute("""
        SELECT
            COUNT(DISTINCT t.datestr) AS train_days,
            MIN(t.datestr) AS first_date,
            MAX(t.datestr) AS last_date,
            COUNT(*) AS total_trains,
            ROUND(AVG(t.duration_s) / 60.0, 1) AS avg_duration_min
        FROM trains t
    """).fetchone()

    first, last = stats[1], stats[2]
    total_days = (datetime.strptime(last, "%Y-%m-%d") - datetime.strptime(first, "%Y-%m-%d")).days + 1
    weeks = total_days / 7.0 if total_days else 1
    freq_per_week = stats[0] / weeks if weeks else 0

    print(f"📅 训练概览")
    print(f"  日期范围:     {first} ~ {last}（{total_days} 天）")
    print(f"  训练天数:     {stats[0]} 天")
    print(f"  训练频率:     {freq_per_week:.1f} 次/周")
    print(f"  总训练条数:   {stats[3]} 次")
    print(f"  平均时长:     {stats[4]} 分钟\n")


def report_titles(conn):
    """训练类型分布"""
    titles = conn.execute("""
        SELECT title, COUNT(*) AS cnt
        FROM trains
        WHERE title IS NOT NULL AND title != ''
        GROUP BY title
        ORDER BY cnt DESC
    """).fetchall()

    print(f"🏋️ 训练类型分布")
    for title, cnt in titles:
        bar = "█" * cnt
        print(f"  {title:20s} {cnt:3d}次 {bar}")
    print()


def report_frequency_by_week(conn):
    """按周统计训练天数"""
    rows = conn.execute("""
        SELECT
            strftime('%Y-%W', datestr) AS week,
            COUNT(DISTINCT datestr) AS days
        FROM trains
        GROUP BY week
        ORDER BY week
    """).fetchall()

    print(f"📆 每周训练天数")
    for week, days in rows:
        bar = "█" * days + "░" * (7 - days)
        print(f"  {week}  {bar}  {days}/7")
    print()


def report_top_movements(conn, limit=15):
    """高频动作"""
    rows = conn.execute("""
        SELECT m.name,
               COUNT(DISTINCT m.train_id) AS sessions,
               COUNT(s.id) AS total_sets,
               ROUND(AVG(s.weight_kg), 1) AS avg_weight
        FROM movements m
        JOIN sets s ON s.movement_id = m.id
        WHERE s.done = 1 AND s.weight_kg IS NOT NULL AND s.weight_kg > 0
        GROUP BY m.name
        ORDER BY sessions DESC, total_sets DESC
        LIMIT ?
    """, (limit,)).fetchall()

    print(f"🏆 高频动作 (Top {limit})")
    print(f"  {'动作':20s} {'训练次数':>8s} {'总组数':>6s} {'平均重量':>8s}")
    print(f"  {'-'*44}")
    for name, sessions, total_sets, avg_w in rows:
        unit = "kg" if avg_w and avg_w < 200 else ""
        w_str = f"{avg_w:.1f}{unit}" if avg_w else "-"
        print(f"  {name:20s} {sessions:>4d}次  {total_sets:>4d}组  {w_str:>8s}")
    print()


def report_progression(conn, movement_name=None):
    """主项重量进展"""
    if movement_name:
        names = [movement_name]
    else:
        names = ["杠铃卧推", "硬拉", "深蹲"]
        # 自动检测实际存在的动作
        existing = {r[0] for r in conn.execute("SELECT DISTINCT name FROM movements").fetchall()}
        names = [n for n in names if n in existing]
        if not names:
            # fallback: 找出练习次数最多的负重动作
            names = [r[0] for r in conn.execute("""
                SELECT m.name FROM movements m
                JOIN sets s ON s.movement_id = m.id
                WHERE s.done = 1 AND s.weight_kg IS NOT NULL AND s.weight_kg > 10
                GROUP BY m.name
                ORDER BY COUNT(DISTINCT m.train_id) DESC
                LIMIT 3
            """).fetchall()]

    for name in names:
        data = conn.execute("""
            SELECT t.datestr, m.name,
                   ROUND(AVG(s.weight_kg), 1) AS avg_w,
                   MAX(s.weight_kg) AS max_w,
                   SUM(s.reps * s.weight_kg) AS volume_kg,
                   COUNT(s.id) AS set_count
            FROM trains t
            JOIN movements m ON m.train_id = t.localid
            JOIN sets s ON s.movement_id = m.id
            WHERE m.name = ? AND s.done = 1 AND s.weight_kg IS NOT NULL AND s.weight_kg > 0
            GROUP BY t.datestr
            ORDER BY t.datestr
        """, (name,)).fetchall()

        print(f"📈 {name} 进展")
        if not data:
            print(f"  （无数据）\n")
            continue

        # best set (max weight)
        best = max(data, key=lambda r: r[3])
        # trend: compare first 3 vs last 3 (simple avg of avg weights)
        if len(data) >= 4:
            early_avg = sum(r[2] for r in data[:3]) / 3
            late_avg = sum(r[2] for r in data[-3:]) / 3
            change = late_avg - early_avg
            arrow = "↑" if change > 1 else ("↓" if change < -1 else "→")
            trend = f"{arrow} {abs(change):.1f}kg"
        else:
            trend = "数据不足"

        print(f"  最佳: {best[3]}kg ({best[0]})")
        print(f"  趋势: {trend}")
        print(f"  训练次数: {len(data)} 次")
        print(f"  最近 5 次:")
        for row in data[-5:]:
            print(f"    {row[0]}  平均 {row[2]}kg  最大 {row[3]}kg  容量 {row[4]:.0f}kg·rep")
        print()


def report_movement_detail(conn, movement_name):
    """单个动作详细进展"""
    report_progression(conn, movement_name)


def report_push_pull_balance(conn, months=2):
    """推/拉/腿 训练量平衡分析"""
    from datetime import timedelta
    latest = conn.execute("SELECT MAX(datestr) FROM trains").fetchone()[0]
    if not latest:
        return
    d = datetime.strptime(latest, "%Y-%m-%d") - timedelta(days=months * 30)
    cutoff = d.strftime("%Y-%m-%d")

    # 按训练标题归类
    rows = conn.execute("""
        SELECT title,
               COUNT(DISTINCT datestr) AS sessions,
               SUM(ms.sets) AS total_sets,
               ROUND(SUM(ms.volume_kg), 0) AS total_volume
        FROM (
            SELECT t.title, t.datestr,
                   COUNT(s.id) AS sets,
                   COALESCE(SUM(s.weight_kg * s.reps), 0) AS volume_kg
            FROM trains t
            JOIN movements m ON m.train_id = t.localid
            JOIN sets s ON s.movement_id = m.id
            WHERE t.datestr >= ? AND s.done = 1
            GROUP BY t.localid, t.title, t.datestr
        ) ms
        GROUP BY ms.title
        ORDER BY total_sets DESC
    """, (cutoff,)).fetchall()

    # 归为 Push / Pull / Legs / Other
    def classify(title):
        t = title or ""
        if any(k in t for k in ["推", "胸", "肩", "三头", "Push", "P1-推", "P2-推", "P3-推"]):
            return "推 (Push)"
        if any(k in t for k in ["拉", "背", "二头", "Pull", "P1-拉", "P2-拉", "P3-拉"]):
            return "拉 (Pull)"
        if any(k in t for k in ["腿", "Legs", "深蹲", "硬拉"]):
            return "腿 (Legs)"
        return "其他"

    groups = defaultdict(lambda: {"sessions": 0, "sets": 0, "volume": 0.0})
    for title, sessions, sets, vol in rows:
        g = classify(title)
        groups[g]["sessions"] += sessions
        groups[g]["sets"] += sets
        groups[g]["volume"] += vol

    print(f"📊 推/拉/腿平衡分析（近 {months} 个月）")
    total_sets = sum(g["sets"] for g in groups.values()) or 1
    for g_name in ["推 (Push)", "拉 (Pull)", "腿 (Legs)", "其他"]:
        g = groups.get(g_name, {"sessions": 0, "sets": 0, "volume": 0.0})
        pct = g["sets"] / total_sets * 100
        bar = "█" * int(pct / 2) + "░" * max(0, 20 - int(pct / 2))
        print(f"  {g_name:15s} {g['sets']:3d}组({pct:4.0f}%) {bar}")

    # 平衡建议
    push_pct = groups.get("推 (Push)", {}).get("sets", 0) / total_sets * 100
    pull_pct = groups.get("拉 (Pull)", {}).get("sets", 0) / total_sets * 100
    legs_pct = groups.get("腿 (Legs)", {}).get("sets", 0) / total_sets * 100
    print()
    if legs_pct < 20:
        print(f"  ⚠ 腿训练量偏少 ({legs_pct:.0f}%)，建议增加腿部训练组数")
    if pull_pct < push_pct * 0.7:
        print(f"  ⚠ 拉/推比例偏低 (拉{pull_pct:.0f}% vs 推{push_pct:.0f}%)，建议增加背部/二头训练量")
    if push_pct > pull_pct * 1.5:
        print(f"  ⚠ 推显著多于拉，注意肩部前后平衡，增加划船/面拉类动作")
    print()


def report_plateau_detection(conn):
    """检测主项平台期"""
    existing = {r[0] for r in conn.execute("SELECT DISTINCT name FROM movements").fetchall()}
    candidates = [n for n in ["杠铃卧推", "硬拉", "深蹲"] if n in existing]
    if not candidates:
        candidates = [r[0] for r in conn.execute("""
            SELECT m.name FROM movements m
            JOIN sets s ON s.movement_id = m.id
            WHERE s.done = 1 AND s.weight_kg IS NOT NULL AND s.weight_kg > 20
            GROUP BY m.name
            ORDER BY COUNT(DISTINCT m.train_id) DESC LIMIT 3
        """).fetchall()]

    print(f"🔍 平台期检测")
    found = False
    for name in candidates:
        sessions = conn.execute("""
            SELECT t.datestr, MAX(s.weight_kg) as max_w
            FROM trains t
            JOIN movements m ON m.train_id = t.localid
            JOIN sets s ON s.movement_id = m.id
            WHERE m.name = ? AND s.done = 1 AND s.weight_kg IS NOT NULL AND s.weight_kg > 0
            GROUP BY t.datestr
            ORDER BY t.datestr DESC
            LIMIT 6
        """, (name,)).fetchall()

        if len(sessions) >= 4:
            recent_max = sessions[0][1]
            older_max = max(s[1] for s in sessions[1:])
            if recent_max <= older_max and older_max > 0:
                decline = (older_max - recent_max) / older_max * 100
                status = "⬇ 下降" if decline > 5 else "→ 持平"
                print(f"  {name}: 近 {len(sessions)} 次最高 {recent_max}kg (峰值 {older_max}kg) {status}")
                found = True

    if not found:
        print(f"  未检测到明显平台期（近期主项仍在进步或数据不足）")
    print()


def report_recent_recommendations(conn):
    """基于近期数据和用户偏好，生成可操作建议"""
    print(f"💡 训练建议")

    # 1. 最近一周训练频率
    last_week = conn.execute("""
        SELECT COUNT(DISTINCT datestr)
        FROM trains
        WHERE datestr >= date('now', '-14 days')
    """).fetchone()[0]
    recent_4w = conn.execute("""
        SELECT COUNT(DISTINCT datestr)
        FROM trains
        WHERE datestr >= date('now', '-28 days')
    """).fetchone()[0]
    avg_weekly = recent_4w / 4.0

    print(f"  频率: 近2周训练 {last_week} 天，近4周平均 {avg_weekly:.1f} 次/周")
    if avg_weekly < 3:
        print(f"   → 建议逐步增加到每周 4 次，优先确保 PPL 各覆盖一次")

    # 2. 最近是否有 deload 信号
    last_3_volume = conn.execute("""
        SELECT t.datestr,
               COALESCE(SUM(s.weight_kg * s.reps), 0) AS volume
        FROM trains t
        JOIN movements m ON m.train_id = t.localid
        JOIN sets s ON s.movement_id = m.id
        WHERE s.done = 1 AND t.datestr >= date('now', '-30 days')
        GROUP BY t.datestr
        ORDER BY t.datestr
    """).fetchall()
    if len(last_3_volume) >= 6:
        recent_avg = sum(r[1] for r in last_3_volume[-3:]) / 3
        older_avg = sum(r[1] for r in last_3_volume[:3]) / 3
        if recent_avg < older_avg * 0.7:
            print(f"  训练量: 近3次平均容量 {recent_avg:.0f} kg·rep（较前3次下降 {100-recent_avg/older_avg*100:.0f}%）")
            print(f"   → 可能是正常的减载或恢复期，无需干预")
        elif recent_avg > older_avg * 1.25:
            print(f"  训练量: 近期容量快速增长 ({recent_avg:.0f} vs {older_avg:.0f})")
            print(f"   → 注意监控恢复，如需减载可降低 40-60% 容量")

    # 3. 检查用户偏好关联
    profile_path = Path(__file__).resolve().parents[1] / "profile.md"
    if profile_path.exists():
        with open(profile_path, "r") as f:
            content = f.read()
        if "小重量" in content and "腿部" in content:
            legs_volume = conn.execute("""
                SELECT COUNT(s.id) FROM trains t
                JOIN movements m ON m.train_id = t.localid
                JOIN sets s ON s.movement_id = m.id
                WHERE s.done = 1 AND t.datestr >= date('now', '-14 days')
                AND (m.name LIKE '%蹲%' OR m.name LIKE '%硬拉%' OR m.name LIKE '%腿%' OR m.name LIKE '%弓步%')
            """).fetchone()[0]
            print(f"  腿部（偏好）: 近2周腿部训练组数 {legs_volume} 组（偏好小重量中次数）")
            print(f"   → 建议腿部动作控制在 10-15 rep，RPE 6-8，优先动作质量")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="分析训记训练数据")
    parser.add_argument("--movement", "-m", type=str, help="查看单个动作进展")
    parser.add_argument("--advice", action="store_true", help="仅输出训练建议")
    args = parser.parse_args()

    conn = get_conn()

    if args.movement:
        report_movement_detail(conn, args.movement)
    elif args.advice:
        report_recent_recommendations(conn)
    else:
        report_overview(conn)
        report_push_pull_balance(conn)
        report_titles(conn)
        report_frequency_by_week(conn)
        report_top_movements(conn)

        existing = {r[0] for r in conn.execute("SELECT DISTINCT name FROM movements").fetchall()}
        main_lifts = [n for n in ["杠铃卧推", "硬拉", "深蹲"] if n in existing]
        if not main_lifts:
            main_lifts = [r[0] for r in conn.execute("""
                SELECT m.name FROM movements m
                JOIN sets s ON s.movement_id = m.id
                WHERE s.done = 1 AND s.weight_kg IS NOT NULL AND s.weight_kg > 20
                GROUP BY m.name
                ORDER BY COUNT(DISTINCT m.train_id) DESC
                LIMIT 3
            """).fetchall()]
        for m in main_lifts:
            report_progression(conn, m)

        report_plateau_detection(conn)
        report_recent_recommendations(conn)

    conn.close()
