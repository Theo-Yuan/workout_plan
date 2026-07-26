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

### 3. 分析训练

```bash
# 完整分析报告
python .agents/db/analyze.py

# 查看某个动作的进展
python .agents/db/analyze.py --movement "杠铃卧推"

# 快速训练建议
python .agents/db/analyze.py --advice
```

### 4. 在 Agent 中使用

在支持 OpenCode / Claude Code 等 AI 工具的项目中，加载 skill 即可获得基于你个人数据的智能分析：

```
skill(name="/train")   # 训练分析 + 训练科学知识库
skill(name="/body")    # 身体数据分析
skill(name="/diet")    # 饮食数据分析
```

Agent 会自动读取 `.agents/profile.md` 了解你的偏好和目标。

---

## 项目结构

```
.agents/
├── profile.md                ← 你的个人档案（已 gitignore）
├── profile.example.md        ← 档案模板（可提交）
├── db/
│   ├── sync_train.py         ← 训练数据同步脚本
│   ├── analyze.py            ← 训练分析脚本
│   └── train.db              ← SQLite 数据库（已 gitignore）
└── skills/
    ├── _shared/
    │   ├── auth.md                   ← 通用鉴权规则
    │   ├── auth.body.md              ← 身体 Key（生成，已 gitignore）
    │   ├── auth.diet.md              ← 饮食 Key（生成，已 gitignore）
    │   ├── auth.train.md             ← 训练 Key（生成，已 gitignore）
    │   ├── error-handling.md         ← 通用错误处理
    │   ├── generate_auth.py          ← Key 注入脚本
    │   └── training-knowledge.md     ← 训练科学知识库
    ├── body.md                ← 训记身体数据 API Skill
    ├── diet.md                ← 训记饮食数据 API Skill
    └── train.md               ← 训记训练数据 API Skill

.env                          ← API Key（已 gitignore）
.env.example                  ← Key 模板
```

---

## 能力

### 当前已有
- ✅ 从训记 API 增量同步训练记录到本地 SQLite
- ✅ 推/拉/腿 训练量平衡分析
- ✅ 主项（卧推、硬拉等）重量进展追踪
- ✅ 平台期检测
- ✅ 基于个人偏好的训练建议
- ✅ 训练科学知识库（强度区间、RPE、渐进超载、Deload 等）

### 计划中
- 📋 写回训练计划：根据分析和偏好生成下一次训练并写入训记
- 🔗 体/训/食数据关联：身体数据 + 训练 + 饮食的交叉分析
- 🧠 更智能的周期化建议

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
