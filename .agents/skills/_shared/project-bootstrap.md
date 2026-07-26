---
description: "可复用的 AI Agent 项目知识基础设施搭建工作流"
---

# Project Bootstrap — 项目知识基础设施搭建

> 从训记训练助手项目提炼的可复用模式。
> 加载此 Skill 后，参考 `.agents/workflows/project-bootstrap.md` 获取完整执行细节。

---

## 一句话摘要

任何需要 "Agent + 个人数据 + 知识库 + 移动端访问" 的项目，都可以用这个 7 步工作流：

```
1. 初始化项目骨架 + gitignore + 环境变量
2. 建立用户画像（profile.md，gitignored）
3. 编写领域 API Skill + 注入 Key
4. 搭建数据管道（sync → SQLite → analyze）
5. 构建结构化知识库（frontmatter + 来源引用）
6. 部署 GitHub Pages（Docsify，移动端可读）
7. 关联加载（Skill → 知识库 → 画像）
```

---

## 完整工作流

详细执行步骤见：

```
.agents/workflows/project-bootstrap.md
```

包含：
- 每阶段的目录结构和文件模板
- `generate_auth.py` 模式
- SQLite 数据库 Schema 设计模式
- `analyze.py` 输出模式
- Docsify 配置（含踩坑记录：不用 relativePath）
- GitHub Pages 最佳实践
- 项目启动检查清单模板

---

## 下次使用

启动新项目时，Agent：

1. 加载此 Skill → 了解整体框架
2. 读 `.agents/workflows/project-bootstrap.md` → 获取详细步骤
3. 逐项执行 Phase 1 → 7
4. 针对新项目领域调整知识库主题和来源
