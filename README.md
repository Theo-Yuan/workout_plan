# 训记 AI 训练助手

将 [训记](https://xunjiapp.cn) 训练/饮食/身体数据与 AI Agent 结合的个人训练分析工具。

> 🎯 **首要目标**: 你的本地个人训练智囊
> 📤 **次要目标**: 便于 GitHub 分享和交流

---

## 快速开始

### 前置条件

- Python 3.8+
- 训记 App 账号（已申请 Open API Key）

### 1. 克隆并配置

```bash
git clone <your-repo>
cd workout_plan

# 填写 API Key（在训记 App 中申请）
cp .env.example .env
# 编辑 .env 填入你的 Key

# 生成鉴权文件
python .agents/skills/_shared/generate_auth.py

# 填写个人档案
cp .agents/profile.example.md .agents/profile.md
# 编辑 .agents/profile.md 填入你的偏好
```

### 2. 同步训练数据

```bash
# 同步近 6 个月的训练记录到本地 SQLite
# 受 API 限频影响（15秒/次），首次同步约需 15-30 分钟
python .agents/db/sync_train.py

# 查看同步状态
python .agents/db/sync_train.py --status

# 增量更新（后续运行只会拉取缺失的日期）
python .agents/db/sync_train.py --months 1
```

### 3. CRUD 操作（CLI 脚本）

```bash
# 查询某天训练（自动处理：本地缓存 → API → 回写缓存）
python .agents/db/query_train.py --date 2026-07-27

# 批量查询日期范围
python .agents/db/query_train.py --range 2026-07-01 2026-07-27

# JSON 格式输出（供 Agent 消费）
python .agents/db/query_train.py --date 2026-07-27 --json

# 写回训练（先 dry-run 验证）
cat training.json | python .agents/db/write_train.py --dry-run

# 确认写入（自动同步到本地缓存）
cat training.json | python .agents/db/write_train.py --confirmed
```

### 4. 在 Agent 中使用

在支持 OpenCode / Claude Code 等 AI 工具的项目中，加载 skill 即可获得基于你个人数据的智能分析：

```
skill(name="/train")   # 训练 API + 训练科学知识库
skill(name="/body")    # 身体数据分析
skill(name="/diet")    # 饮食数据分析
```

Agent 会自动读取 `.agents/profile.md` 了解你的偏好和目标。

Agent 的分析能力基于：
- 本地 SQLite 数据 → 直接在库上做 SQL 查询推理
- 知识库 → `knowledge/`（训练科学）
- 用户画像 → `.agents/profile.md`

---

## 项目结构

```
.agents/
├── profile.md                ← 你的个人档案（已 gitignore）
├── profile.example.md        ← 档案模板（可提交）
├── db/
│   ├── sync_train.py         ← 批量历史同步脚本
│   ├── query_train.py        ← 按天查询（cache-through）
│   ├── write_train.py        ← 写回训练（dry-run → confirmed）
│   ├── analyze.py            ← [已废弃] 分析由 Agent 直接推理
│   └── train.db              ← SQLite 数据库（已 gitignore）
├── skills/
│   ├── _shared/
│   │   ├── auth.md                   ← 通用鉴权规则
│   │   ├── auth.body.md              ← 身体 Key（生成，已 gitignore）
│   │   ├── auth.diet.md              ← 饮食 Key（生成，已 gitignore）
│   │   ├── auth.train.md             ← 训练 Key（生成，已 gitignore）
│   │   ├── error-handling.md         ← 通用错误处理
│   │   └── generate_auth.py          ← Key 注入脚本
│   ├── body.md                ← 训记身体数据 API Skill
│   ├── diet.md                ← 训记饮食数据 API Skill
│   └── train.md               ← 训记训练数据 API Skill
└── workflows/
    └── project-bootstrap.md

knowledge/                    ← 训练科学知识库（项目内容）
├── 00-快速导航.md
├── 01-训练核心原则.md ~ 99-来源文献.md
└── WORKFLOW.md

tmp/                          ← 临时文件（已 gitignore）
.env / .env.example
index.html / _sidebar.md      ← GitHub Pages (Docsify)
```

---

## 能力

### 当前已有
- ✅ `query_train.py` — cache-through 查询（本地→API→回写缓存，防缓存穿透）
- ✅ `write_train.py` — 写回训练（dry-run 验证 → 确认写入 → 自动同步）
- ✅ `sync_train.py` — 批量历史同步
- ✅ Agent 直接在 SQLite 上推理分析（不依赖固定规则脚本）
- ✅ 训练科学知识库（强度区间、RPE、渐进超载、Deload 等）
- ✅ GitHub Pages + Docsify 移动端知识站

### 计划中
- 🔗 体/训/食数据关联：身体数据 + 训练 + 饮食的交叉分析
- 🧠 更智能的 Agent 驱动周期化建议

---

## 分享说明

本仓库包含：

| 内容 | 是否提交 | 说明 |
|------|----------|------|
| Skill 文件（body/diet/train） | ✅ 提交 | API 使用指南，不含 Key |
| 知识库（training-knowledge.md） | ✅ 提交 | 通用训练科学 |
| 同步/分析脚本 | ✅ 提交 | 可复用的 Python 工具 |
| 档案模板（profile.example.md） | ✅ 提交 | 不含个人数据 |
| `.env.example` | ✅ 提交 | Key 模板 |
| **API Key** | ❌ 已 gitignore | 在 `.env` 和 `auth.*.md` 中 |
| **训练数据** | ❌ 已 gitignore | 在 `train.db` 中 |
| **个人档案** | ❌ 已 gitignore | 在 `profile.md` 中 |

> fork 后只需填自己的 Key、同步自己的数据、改自己的 profile 即可使用。
