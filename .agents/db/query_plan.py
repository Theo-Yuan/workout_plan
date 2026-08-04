#!/usr/bin/env python3
"""
训记官方计划查询脚本 — 读取用户 App 中的真实训练计划。

官方计划是「日期 → 训练日/休息日」的真实映射（用户可在训记 App 中查看/调整），
与本地 SQLite 中「实际完成训练」不同。预告/分析时应两者结合，以实际进度为准。

限频说明：训记 API 有频率限制（约 15 秒/次）。本脚本按「当天」缓存官方计划，
当天首次拉取后写入本地缓存，后续调用直接读缓存，避免频繁触发限频。

用法:
    python .agents/db/query_plan.py --list
    python .agents/db/query_plan.py --get --ref platform:70 --start 2026-08-01 --end 2026-08-10
    python .agents/db/query_plan.py --today            # 今天前7天 ~ 后30天（含动作）
    python .agents/db/query_plan.py --today --no-movements   # 仅日历，不含动作
    python .agents/db/query_plan.py --today --refresh  # 强制刷新缓存
    python .agents/db/query_plan.py --gaps             # 对照实际训练，找出漏练的训练日
"""

import argparse
import gzip
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DB_DIR.parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
API_URL = "https://api.xunjiapp.cn/open/plan/query_gzip"
CACHE_FILE = DB_DIR / "plan_cache.json"
TRAIN_DB_PATH = DB_DIR / "train.db"


def load_api_key() -> str:
    if not ENV_FILE.exists():
        print(f"[错误] 找不到 {ENV_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("XUNJI_TRAIN_API_KEY") and "=" in line:
                val = line.split("=", 1)[1].strip()
                if val and not val.startswith("your_"):
                    return val
    print("[错误] XUNJI_TRAIN_API_KEY 未设置", file=sys.stderr)
    sys.exit(1)


def _call(key: str, body: dict) -> dict:
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            text = raw.decode("utf-8")
            if "too frequent" in text.lower():
                err = json.loads(text)
                return {"__rate_limited__": True, "retry_after_ms": err.get("retry_after_ms", 15000)}
        except Exception:
            pass
        print(f"HTTP {e.code}: {raw.decode('utf-8', errors='replace')[:300]}", file=sys.stderr)
        sys.exit(1)


def _read_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_cache(cache: dict):
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def get_plan_cached(key: str, ref: str, start: str, end: str, movements: bool,
                    refresh: bool = False) -> list:
    """读取日期范围计划，带当天缓存。返回 days 列表。"""
    today = date.today().isoformat()
    cache_key = f"{ref}|{start}|{end}|{movements}"

    if not refresh:
        cache = _read_cache()
        entry = cache.get(cache_key)
        if entry and entry.get("cache_date") == today:
            return entry.get("days", [])

    data = _call(key, {
        "schema_version": "plan_open_api_v1",
        "action": "get",
        "plan_ref": ref,
        "start_date": start,
        "end_date": end,
        "include_movements": movements,
    })
    if data.get("__rate_limited__"):
        # 限频时回退到缓存（若有）
        cache = _read_cache()
        entry = cache.get(cache_key)
        if entry:
            return entry.get("days", [])
        print("限频且无缓存", file=sys.stderr)
        return []

    res = data.get("res", {})
    days = res.get("days", [])

    cache = _read_cache()
    cache[cache_key] = {"cache_date": today, "days": days}
    _write_cache(cache)
    return days


def list_plans(key: str):
    data = _call(key, {"schema_version": "plan_open_api_v1", "action": "list"})
    res = data.get("res", {})
    plans = res.get("plans", [])
    if not plans:
        print("(无活跃计划)")
        return
    for p in plans:
        print(json.dumps({
            "plan_ref": p.get("plan_ref"),
            "title": p.get("title"),
            "status": p.get("status"),
            "start_date": p.get("start_date"),
            "end_date": p.get("end_date"),
            "next_scheduled_training_date": p.get("next_scheduled_training_date"),
            "day_count": p.get("day_count"),
            "training_day_count": p.get("training_day_count"),
        }, ensure_ascii=False))


def find_missed_sessions(days: list, train_db_path: Path = TRAIN_DB_PATH) -> list:
    """对照官方计划与实际训练，找出「计划安排了训练日但实际未执行」的漏练。

    判断规则：计划 day_type=training 且 datestr 为过去日期，但本地 SQLite
    train.db 中该日期没有任何训练记录 → 记为漏练。

    注意：本地库若未同步过当天（sync_meta 无 synced_ 标记）则跳过，避免误报。
    """
    if not train_db_path.exists():
        return []
    today = date.today().isoformat()
    conn = sqlite3.connect(str(train_db_path))
    missed = []
    try:
        for d in days:
            ds = d.get("datestr")
            if not ds or ds >= today:
                continue
            if d.get("day_type") != "training":
                continue
            synced = conn.execute(
                "SELECT 1 FROM sync_meta WHERE key = ?", (f"synced_{ds}",)
            ).fetchone()
            if not synced:
                continue
            has_train = conn.execute(
                "SELECT 1 FROM trains WHERE datestr = ? LIMIT 1", (ds,)
            ).fetchone()
            if not has_train:
                missed.append({
                    "datestr": ds,
                    "workout_name": (d.get("workout") or {}).get("name"),
                })
    finally:
        conn.close()
    return missed


def _print_days(days: list, movements: bool):
    for d in days:
        row = {
            "datestr": d.get("datestr"),
            "day_type": d.get("day_type"),
            "completion_status": d.get("completion_status"),
            "workout_name": (d.get("workout") or {}).get("name"),
        }
        if movements and d.get("workout"):
            row["movements"] = [
                {"name": m.get("name"), "target_sets": m.get("target_sets"),
                 "target_reps": m.get("target_reps")}
                for m in d["workout"].get("movements", [])
            ]
        print(json.dumps(row, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="训记官方计划查询")
    parser.add_argument("--list", action="store_true", help="列出所有计划")
    parser.add_argument("--get", action="store_true", help="读取日期范围计划")
    parser.add_argument("--today", action="store_true", help="读取今天前7天~后30天")
    parser.add_argument("--ref", default="platform:70", help="计划引用，默认 platform:70")
    parser.add_argument("--start", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--no-movements", action="store_true", help="不含动作，仅日历")
    parser.add_argument("--refresh", action="store_true", help="强制刷新缓存")
    parser.add_argument("--gaps", action="store_true",
                        help="对照实际训练，找出计划安排了但未执行的训练日（漏练检测）")
    args = parser.parse_args()

    key = load_api_key()

    if args.gaps:
        today = date.today()
        start = (today - timedelta(days=7)).isoformat()
        end = today.isoformat()
        days = get_plan_cached(key, args.ref, start, end, False, refresh=args.refresh)
        missed = find_missed_sessions(days)
        if not missed:
            print("(无漏练训练日)")
        else:
            for m in missed:
                print(json.dumps(m, ensure_ascii=False))
        return

    if args.list:
        list_plans(key)
        return

    if args.today:
        today = date.today()
        start = (today - timedelta(days=7)).isoformat()
        end = (today + timedelta(days=30)).isoformat()
        days = get_plan_cached(key, args.ref, start, end, not args.no_movements,
                               refresh=args.refresh)
        _print_days(days, not args.no_movements)
        return

    if args.get:
        if not args.start or not args.end:
            print("--get 需要 --start 和 --end", file=sys.stderr)
            sys.exit(1)
        days = get_plan_cached(key, args.ref, args.start, args.end,
                               not args.no_movements, refresh=args.refresh)
        _print_days(days, not args.no_movements)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
