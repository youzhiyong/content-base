# 忆往昔 · 中华文明内容仓库（共创）

> **温故而知新。**
> 为往圣继绝学——以可共创、可溯源、可审核的方式，收录中华文明的核心事实层内容。

本仓库是「忆往昔」（YIWANGXI）知识平台的内容共创仓库，收录**古籍原文、诗词、历史人物、核心概念**等客观事实层内容。知识卡片、知识图谱等程序加工产物不在此仓库（由主平台数据库保持）。

## 这是什么

| | 说明 |
|---|---|
| **收录内容** | 古籍原文（公版校点本）、诗词、历史人物条目、核心概念词条 |
| **不收录** | 知识卡片、知识图谱关系、营销内容（程序加工产物，主平台数据库保持） |
| **核心原则** | 原典为根、来源可溯、人工审核、AI 辅助但永不署名 |
| **协作方式** | Git PR + 认领制 + 审阅制 + CI 门禁 |

## 快速开始

```bash
# 1. 克隆
git clone <本仓库地址>
cd <仓库名>

# 2. 自检（提交前必跑）
python tools/check.py          # 必须 0 错误

# 3. 看看缺什么 → 认领 → 提 PR
```

## 如何参与

- **第一次来**：读 [CONTRIBUTING.md](CONTRIBUTING.md)（贡献指南）→ [OWNERS.md](OWNERS.md)（治理与裁决）
- **找活干**：看 `classics/` 哪些经典缺章节全文，或开 issue 认领
- **提 PR**：遵循 [CONTRIBUTING.md](CONTRIBUTING.md) 的检查清单 + 完整流程 SOP
- **贡献者注册**：第一个 PR 里把自己加入 [AUTHORS.yaml](AUTHORS.yaml)，之后全仓复用你的 ID 署名

## 目录结构

```
├── README.md               # 本文件
├── CONTRIBUTING.md         # 贡献指南（署名门槛 / AI 规则 / 认领制）
├── OWNERS.md               # 维护者名单与裁决规则
├── AUTHORS.yaml            # 全仓人员注册表（一人一 ID）
├── LICENSE                 # 分层协议（原文公版 / 人物 CC BY 4.0 / 译文 CC BY-SA 4.0 / 工具 MIT）
├── schema/                 # JSON Schema（check.py 校验依据，自发现）
├── classics/               # 古籍原文（一经典一目录：classic.md + chapters/）
├── entities/               # 事实层实体
│   ├── persons/            #   历史人物条目
│   └── concepts/           #   核心概念词条
├── poetry/                 # 诗词（预留）
└── tools/                  # 校验/同步工具（check.py / sync.py / 生成脚本）
```

## 质量保证

- **CI 门禁**：PR 自动跑 `check.py`（schema 校验 + 引用完整性 + AUTHORS 引用 + 状态机），0 错误才可合并。
- **可信度分级**：S（公版定本）/ A（主流观点）/ B（一般说法）/ C（存疑）；C 级不可发布。
- **AI 规则**：AI 辅助录入必须标 `ai_used`，AI 永不署名，AI 初稿必须人类审核后才能离开 DRAFT。

## 协议

内容按类型分层许可（详见 [LICENSE](LICENSE)）：古籍原文=公有领域 / 人物条目=CC BY 4.0 / 译文注释=CC BY-SA 4.0 / 工具与 schema=MIT。使用请遵守署名义务。

---

*忆往昔 · 为往圣继绝学*
