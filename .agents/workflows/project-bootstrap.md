---
description: "AI Agent 项目知识基础设施搭建工作流 — 可复用于个人理财、英语学习等任何个人知识项目"
version: 1
updated: 2026-07-26
---

# 项目知识基础设施搭建工作流

> 从训记训练助手项目中提炼的可复用模式。
> 适用于任何需要 "Agent + 个人数据 + 知识库 + 移动端访问" 的项目。

---

## 整体架构

```
.agents/                  ← AI Agent 工作目录
├── profile.md            ← 用户画像（gitignored）
├── profile.example.md    ← 画像模板
├── db/                   ← 数据管道
│   ├── sync.py           ←   数据拉取脚本
│   ├── analyze.py        ←   数据分析脚本
│   └── data.db           ←   SQLite 数据库（gitignored）
├── skills/               ← Agent Skill
│   ├── domain.md         ←   领域 API Skill（主 skill）
│   └── _shared/          ←   共享模块
│       ├── auth.md
│       ├── error-handling.md
│       ├── generate_auth.py
│       └── project-bootstrap.md  ← 本文档的 skill 版
├── knowledge/            ← 知识库
│   ├── 00-快速导航.md     ←   人类入口 + Agent 索引
│   ├── 01-主题.md         ←   每章一个文件，frontmatter + 叙述体
│   ├── 99-来源文献.md     ←   所有来源链接
│   └── WORKFLOW.md       ←   知识库维护协议
└── workflows/            ← 可复用工作流
    └── project-bootstrap.md  ← 本文档

.env                      ← API Key（gitignored）
.env.example              ← Key 模板
.gitignore
README.md                 ← 项目入口
index.html                ← Docsify（GitHub Pages）
_sidebar.md               ← Docsify 侧边栏
.nojekyll                 ← 禁用 Jekyll
404.html                  ← SPA 兜底
```

---

## Phase 1: 项目初始化

### 1.1 创建目录骨架

```
mkdir -p .agents/{db,skills/_shared,knowledge/_inbox,workflows}
touch .gitignore .env.example README.md
```

### 1.2 配置 `.gitignore`

```
# API Key
.env

# 鉴权生成文件（含真实 Key）
.agents/skills/_shared/auth.*.md

# 本地数据库（含个人数据）
.agents/db/*.db

# 个人画像
.agents/profile.md
```

### 1.3 配置 `.env.example`

```bash
# 从各平台申请的 API Key
DOMAIN_API_KEY=your_key_here
```

---

## Phase 2: 用户画像

### 2.1 创建 `profile.example.md`

```markdown
---
version: 1
updated: YYYY-MM-DD
---

# 用户档案

## 当前状态
- 水平: _（如：理财新手 / 英语四级）_
- 目标: _（如：雅思 6.5 / 被动收入覆盖生活费）_
- 时间投入: _每周几小时_

## 偏好
- _记录你的学习/使用偏好_
- _例如：偏好视频学习 vs 阅读_

## 历史反馈记录
| 日期 | 来源 | 内容 |
|---|---|---|
```

### 2.2 创建 `profile.md`

复制 `profile.example.md` → `profile.md`，填入真实数据。此文件已在 `.gitignore` 中。

---

## Phase 3: Skill 层

### 3.1 确定数据源

列出项目涉及的 API / 数据源：

| 项目 | 可能的数据源 |
|------|-------------|
| 个人理财 | 银行流水、基金/股票 API、记账 App |
| 英语学习 | 词典 API、背单词 App、雅思模考网站 |

### 3.2 编写 Domain Skill

每个 Skill 文件结构：

```markdown
---
description: "一句话说明"
---

# Skill 名称

## 原则
- Agent 使用此 Skill 的规则

@_shared/auth.md
@_shared/auth.domain.md

## 接口
- 列出所有 API 端点

## 数据说明
- 字段含义、单位、格式

@_shared/error-handling.md
```

### 3.3 注入 API Key

```bash
# 1. 在 .env 中填写 Key
# 2. 编写 generate_auth.py 从 .env 读取并生成 auth.xxx.md
# 3. 将 auth.xxx.md 加入 .gitignore
```

`generate_auth.py` 模式：

```python
import os
from pathlib import Path

env = {}
with open(Path(__file__).parents[3] / ".env") as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k] = v

key = env.get("DOMAIN_API_KEY", "{{PLACEHOLDER}}")
output = f"""### Domain Key
- 请求头: `Authorization: Bearer {key}`"""

with open(Path(__file__).parent / "auth.domain.md", "w") as f:
    f.write(output + "\n")
```

---

## Phase 4: 数据管道

### 4.1 设计数据库 Schema

```sql
-- SQLite 标准模式
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    field1 TEXT,
    field2 REAL
);
CREATE INDEX IF NOT EXISTS idx_records_date ON records(date);
```

### 4.2 编写同步脚本 `sync.py`

关键模式：
- 增量同步（记录已同步的日期，跳过重复）
- 限频控制（sleep API 要求的间隔）
- 写入 SQLite

### 4.3 编写分析脚本 `analyze.py`

输出模式：
- 概览（总量、频率、趋势）
- 分类分布
- 主项进展
- 异常/平台期检测
- 个性化建议

支持参数：
```bash
python .agents/db/analyze.py                # 完整报告
python .agents/db/analyze.py --advice       # 仅建议
python .agents/db/analyze.py --detail "xxx" # 单项分析
```

---

## Phase 5: 知识库

### 5.1 目录结构

```
knowledge/
├── 00-快速导航.md    ← 人类从这里开始 + Agent 索引
├── 01-核心概念.md    ← 每个文件一个主题
├── 02-实践方法.md
├── 03-...
├── 99-来源文献.md    ← 所有来源的可追溯链接
├── WORKFLOW.md      ← 知识库维护协议
└── _inbox/          ← 原始收集暂存区
```

### 5.2 文件格式

```markdown
---
type: principle | guide | reference
tags: [标签1, 标签2]
sources: [S1]
updated: YYYY-MM-DD
---

# 标题

自然叙述体，关键信息前置。
数据用 **加粗** 突出。

每条知识标注来源： [来源: S1-作品名]
```

### 5.3 来源文献

```markdown
## S1: 来源名称
| 引用标识 | 作品 | 链接 |
|----------|------|------|
| S1-主题 | 具体内容 | URL |
```

### 5.4 知识库维护工作流

```
收集 → 归类 → 精炼 → 索引 → 调用
  │       │       │       │       │
_inbox/  分类    来源     更新    按需
收集     主题    标注     _index   加载
```

详见 `knowledge/WORKFLOW.md`。

---

## Phase 6: GitHub Pages

### 6.1 创建 Docsify 入口

`index.html`（放项目根目录）：

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>项目知识库</title>
  <link rel="stylesheet" href="//cdn.jsdelivr.net/npm/docsify@4/lib/themes/vue.css">
</head>
<body>
  <div id="app"></div>
  <script src="//cdn.jsdelivr.net/npm/docsify@4/lib/docsify.min.js"></script>
  <script>
    window.$docsify = {
      name: '📚 项目知识库',
      repo: 'https://github.com/USER/REPO',
      basePath: '/REPO/',
      loadSidebar: true,
      subMaxLevel: 3,
      search: { placeholder: '搜索...', noData: '未找到结果' },
      homepage: 'README.md',
    };
  </script>
  <script src="//cdn.jsdelivr.net/npm/docsify@4/lib/plugins/search.min.js"></script>
</body>
</html>
```

### 6.2 创建侧边栏

`_sidebar.md`（放项目根目录）：

```markdown
- [🏠 首页](README.md)
- **知识库**
  - [📖 快速导航](knowledge/00-快速导航.md)
  - [📖 章节](knowledge/01-xxx.md)
```

### 6.3 配置 GitHub Pages

```bash
# 1. 创建 .nojekyll（空文件，放根目录）
touch .nojekyll

# 2. 提交并推送
git add -A && git commit -m "init: project bootstrap"
git push

# 3. 启用 Pages（serve from root）
gh repo create REPO --public --source=. --push --remote=origin
# 或
gh api repos/USER/REPO/pages -X POST --input - <<'EOF'
{"source":{"branch":"main","path":"/"}}
EOF
```

### 6.4 注意事项

- **不要用 `relativePath: true`**——会导致侧边栏链接路径重复拼接
- `.nojekyll` 必须在项目根目录，确保 dotfile 和 `_sidebar.md` 被正常服务
- 根目录模式让 Docsify 直接引用 `knowledge/` 的原始文件，单一数据源

---

## Phase 7: Skill 加载与 Agent 调用

### 主 Skill 中引用知识库和画像

```markdown
> **知识库**: 另见 `knowledge/00-快速导航.md`
> **用户画像**: 另见 `.agents/profile.md`
```

Agent 调用流程：

```
用户提问 → 加载 domain skill
        → 看到知识库和画像引用
        → 用 Read 工具加载 00-快速导航.md
        → 判断需要哪个知识文件
        → 按需加载具体文件
        → 结合 profile 和数据库数据输出
```

---

## 附录：各项目启动检查清单

### 个人理财项目

| 项 | 状态 |
|----|------|
| 确定数据源（记账 App API？银行流水？） | ☐ |
| 编写理财 API Skill | ☐ |
| 同步账户数据到本地 SQLite | ☐ |
| 知识库：理财原则（资产配置、复利、风险） | ☐ |
| 知识库：投资工具（基金、股票、债券） | ☐ |
| 来源：收集你信任的理财博主/书籍 | ☐ |
| 画像：记录你的资产状况和目标 | ☐ |
| GitHub Pages 搭建 | ☐ |

### 英语学习项目

| 项 | 状态 |
|----|------|
| 确定数据源（词典 API？学习记录？） | ☐ |
| 编写英语学习 Skill | ☐ |
| 同步学习记录到本地 SQLite | ☐ |
| 知识库：语法体系 | ☐ |
| 知识库：雅思应试技巧 | ☐ |
| 知识库：学习策略 | ☐ |
| 来源：收集你信任的英语学习资源 | ☐ |
| 画像：记录你的水平和目标 | ☐ |
| GitHub Pages 搭建 | ☐ |

---

> 本文档本身就是这个工作流的实例。
> 下次启动新项目时，Agent 将此文件作为 roadmap 逐项执行。
