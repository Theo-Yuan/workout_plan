#!/usr/bin/env python3
"""
训记训练写回脚本

接收训练 JSON，发送到训记 API，写回后同步到本地缓存。
支持 dry_run 模式供 Agent 验证后再确认写入。

用法:
    cat training.json | python .agents/db/write_train.py
    python .agents/db/write_train.py --file training.json
    python .agents/db/write_train.py --dry-run < training.json
    python .agents/db/write_train.py --confirmed < training.json
"""

import gzip
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

DB_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DB_DIR.parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
DB_PATH = DB_DIR / "train.db"
API_URL = "https://trains.xunjiapp.cn/api_upsert_trains_for_llm_v2"
RATE_LIMIT = 45  # 写回限频 45 秒


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


def _init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS trains (
            localid    INTEGER PRIMARY KEY,
            datestr    TEXT NOT NULL,
            title      TEXT,
            start_ms   INTEGER,
            end_ms     INTEGER,
            duration_s INTEGER,
            note       TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_trains_datestr ON trains(datestr);
        CREATE TABLE IF NOT EXISTS movements (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            train_id   INTEGER NOT NULL REFERENCES trains(localid),
            name       TEXT NOT NULL,
            idx        INTEGER,
            difficulty TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_movements_train ON movements(train_id);
        CREATE TABLE IF NOT EXISTS sets (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            movement_id  INTEGER NOT NULL REFERENCES movements(id),
            idx          INTEGER,
            done         INTEGER,
            weight_kg    REAL,
            reps         INTEGER,
            rpe          TEXT,
            time_s       INTEGER,
            self_weight  INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_sets_movement ON sets(movement_id);
    """)
    conn.commit()


def _get_synced_dates(conn: sqlite3.Connection) -> set:
    rows = conn.execute("SELECT DISTINCT datestr FROM trains").fetchall()
    return {r[0] for r in rows}


def _build_request_body(data, confirmed: bool = False) -> dict:
    body = {
        "schema_version": "train_open_api_v2",
        "client_request_id": f"agent_{int(time.time())}",
        "dry_run": not confirmed,
    }
    if isinstance(data, list):
        body["res"] = data
    elif isinstance(data, dict):
        res = data.get("res", data)
        if isinstance(res, list):
            body["res"] = res
        elif isinstance(res, dict) and "trains" in res:
            body["res"] = res["trains"]
        else:
            body["res"] = [res]
    else:
        body["res"] = [data]
    return body


def _fetch_api(api_key: str, body: dict) -> Optional[dict]:
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
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
                return {"__rate_limited__": True, "retry_after_ms": err.get("retry_after_ms", 45000)}
        except Exception:
            pass
        print(f"HTTP {e.code}: {raw.decode('utf-8', errors='replace')[:500]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"请求异常: {e}", file=sys.stderr)
        return None


def _sync_written_dates(api_key: str, datestrs: set):
    import subprocess
    query_script = DB_DIR / "query_train.py"
    for d in sorted(datestrs):
        print(f"  同步 {d} 到本地缓存...")
        result = subprocess.run(
            [sys.executable, str(query_script), "--date", d, "--force-api", "--json"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  ⚠ 同步失败: {result.stderr.strip()}", file=sys.stderr)


def write_trains(api_key: str, data: dict, confirmed: bool = False) -> dict:
    body = _build_request_body(data, confirmed)
    datestrs = set()
    for t in body["res"]:
        if isinstance(t, dict) and "datestr" in t:
            datestrs.add(t["datestr"])

    result = _fetch_api(api_key, body)
    if result is None:
        return {"status": "error", "message": "API request failed"}

    if result.get("__rate_limited__"):
        return {"status": "rate_limited", "retry_after_ms": result["retry_after_ms"]}

    if confirmed and result.get("success"):
        print(f"✓ 写回成功，同步 {len(datestrs)} 天到本地缓存...")
        _sync_written_dates(api_key, datestrs)

    return result


def print_summary(body: dict):
    trains = body.get("res", [])
    print(f"📋 写回摘要 (dry_run)")
    print(f"  训练条数: {len(trains)}")
    for t in trains:
        ds = t.get("datestr", "?")
        title = t.get("title", "未命名")
        movements = t.get("movements", [])
        print(f"  📅 {ds} {title} ({len(movements)} 个动作)")
        for m in movements:
            sets = m.get("sets", [])
            name = m.get("name", "?")
            print(f"    {name} ({len(sets)} 组)")
            for s in sets[:3]:
                w = s.get("weight", s.get("weight_kg", ""))
                r = s.get("reps", "")
                done = "✓" if s.get("done") else "○"
                print(f"      {done} {w}{'kg' if w else ''} × {r}" if w else f"      {done} {r}reps")
            if len(sets) > 3:
                print(f"      ... 还有 {len(sets)-3} 组")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="写回训练数据到训记")
    parser.add_argument("--file", type=str, help="从 JSON 文件读取")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="仅验证不写入（默认）")
    parser.add_argument("--confirmed", action="store_true",
                        help="确认写入（跳过 dry_run）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    if args.confirmed:
        args.dry_run = False

    if args.file:
        with open(args.file, encoding="utf-8") as f:
            data = json.load(f)
    else:
        if sys.stdin.isatty():
            print("从 stdin 读取训练 JSON...（Ctrl+D 结束）", file=sys.stderr)
        data = json.load(sys.stdin)

    api_key = load_api_key()
    body = _build_request_body(data, confirmed=args.confirmed)

    if args.dry_run:
        if args.json:
            print(json.dumps(body, ensure_ascii=False, indent=2))
        else:
            print_summary(body)
            print("\n确认写入请加 --confirmed 参数")
        return

    result = write_trains(api_key, data, confirmed=True)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result.get("success"):
            print("✓ 写回成功")
        elif result.get("status") == "rate_limited":
            retry = result["retry_after_ms"] / 1000
            print(f"⏳ 限频，请等 {retry:.0f}s 后重试")
        else:
            print(f"✗ 写回失败: {result}")


if __name__ == "__main__":
    main()
