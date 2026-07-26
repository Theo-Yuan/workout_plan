#!/usr/bin/env python3
"""
训记 Open API Auth 生成器

从 .env 读取 API Key，为每个 skill 生成独立的 auth 片段。
生成的 auth 文件包含真实 Key，已被 .gitignore 排除。

用法:
    python .agents/skills/_shared/generate_auth.py

配置:
    确保项目根目录存在 .env 文件，定义如下变量:
        XUNJI_BODY_API_KEY
        XUNJI_DIET_API_KEY
        XUNJI_FOOD_SEARCH_API_KEY
        XUNJI_TRAIN_API_KEY
"""

import os
import sys
from pathlib import Path

# ── 路径 ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"
OUTPUT_DIR = Path(__file__).resolve().parent
SHARED_AUTH = OUTPUT_DIR  # _shared/ 目录

# ── 读取 .env ─────────────────────────────────────
def load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        print(f"[错误] 找不到 .env 文件: {path}")
        print(f"       请复制 .env.example 为 .env 并填入 Key")
        sys.exit(1)

    env: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


# ── 生成 Auth 片段 ────────────────────────────────
def render_auth_body(env: dict) -> str:
    key = env.get("XUNJI_BODY_API_KEY", "{{XUNJI_BODY_API_KEY}}")
    return f"""### 身体数据 Key
- 请求头: `Authorization: Bearer {key}`
- 也兼容请求头 `x-api-key`。"""


def render_auth_diet(env: dict) -> str:
    key = env.get("XUNJI_DIET_API_KEY", "{{XUNJI_DIET_API_KEY}}")
    search_key = env.get("XUNJI_FOOD_SEARCH_API_KEY", "{{XUNJI_FOOD_SEARCH_API_KEY}}")
    return f"""### 饮食记录 Key（查询/写回/自定义食物/模板）
- 请求头: `Authorization: Bearer {key}`

### 食物搜索 Key
- 请求头: `Authorization: Bearer {search_key}`
- 饮食记录接口也兼容请求头 `x-api-key`；食物搜索接口也兼容 `x-agent-key` 或 `x-api-key`。"""


def render_auth_train(env: dict) -> str:
    key = env.get("XUNJI_TRAIN_API_KEY", "{{XUNJI_TRAIN_API_KEY}}")
    return f"""### 训练数据 Key
- 请求头: `Authorization: Bearer {key}`
- 也兼容请求头 `x-api-key`。"""


# ── 写入文件 ──────────────────────────────────────
GENERATORS = {
    "auth.body.md":  render_auth_body,
    "auth.diet.md":  render_auth_diet,
    "auth.train.md": render_auth_train,
}


def main():
    env = load_dotenv(ENV_FILE)

    keys_present = sum(1 for k in ["XUNJI_BODY_API_KEY", "XUNJI_DIET_API_KEY",
                                   "XUNJI_FOOD_SEARCH_API_KEY", "XUNJI_TRAIN_API_KEY"]
                       if env.get(k) and "your_" not in env[k])
    print(f"[信息] 读取到 {keys_present}/4 个 Key")

    for filename, renderer in GENERATORS.items():
        content = renderer(env)
        output_path = SHARED_AUTH / filename
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content + "\n")
        print(f"  ✔  生成 {filename}")

    print(f"\n完成。文件已输出到 {SHARED_AUTH}")
    print("提示: 生成的 auth.*.md 包含真实 Key，已加入 .gitignore 不会提交。")


if __name__ == "__main__":
    main()
