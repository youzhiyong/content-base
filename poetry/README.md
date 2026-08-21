# poetry/ — 诗词曲赋(预留)

诗词属于**事实层恒量**(公版文本),后续纳入本仓库共创校对。

结构规划:诗词体量与古籍不同(一篇一作品),建议 `poetry/{slug}/` 一作者一目录:

```
poetry/
├── lishangyin/           # 作者 slug
│   ├── author.md         # 作者小传(事实字段)
│   └── works/            # 作品,一诗一文件
│       ├── 001-jinse.md
│       └── ...
```

单作品文件格式(与经典章节同构):

```yaml
---
poet_slug: lishangyin
title: 锦瑟
dynasty: tang
era_slug: tang        # 引用 entities/eras/{slug}
form: 七言律诗
review_status: DRAFT
credibility_level: S
---
## 原文
锦瑟无端五十弦，一弦一柱思华年。……

## 今译
(可选)

## 注释
(可选)
```

> 本目录当前为空,待 M3 阶段与经典全文同步启动。
