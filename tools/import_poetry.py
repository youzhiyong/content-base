#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_poetry.py — 从 chinese-poetry 数据集导入精选唐宋名篇到 poetry/{poet_slug}/works/{slug}.md

- 数据源: https://github.com/chinese-poetry/chinese-poetry (MIT 类开放许可,公版文本)
- 繁->简: hanziconv
- 图谱关联: 主题关键词 -> 知识图谱概念(entities/concepts/{slug}) -> 八维 domain
- 门禁: 导入后跑 check.py 校验

用法:
  python tools/import_poetry.py            # 导入 CURATED 名单(默认)
  python tools/import_poetry.py --dry      # 只统计可命中数量,不写文件
  python tools/import_poetry.py --max-files 70 --max-per-poet 15
"""
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from hanziconv import HanziConv

ROOT = Path(__file__).resolve().parent.parent
POETRY = ROOT / "poetry"
TODAY = "2026-08-22"

MAX_FILES = 70       # 每个数据源最多扫描的文件数
MAX_PER_POET = 15    # 每位诗人最多收录作品数

# 精选唐宋顶流诗人(兼顾传播度 + 与八维/概念的关联潜力)
# person: 若作者在 entities/persons/ 已存在则可同名复用
CURATED = {
    "libai":       {"name": "李白",   "dynasty": "tang", "domain": "shenmei"},
    "dufu":        {"name": "杜甫",   "dynasty": "tang", "domain": "rendao"},
    "wangwei":     {"name": "王维",   "dynasty": "tang", "domain": "tiandao"},
    "baijuyi":     {"name": "白居易", "dynasty": "tang", "domain": "rendao"},
    "lishangyin":  {"name": "李商隐", "dynasty": "tang", "domain": "shenmei"},
    "menghaoran":  {"name": "孟浩然", "dynasty": "tang", "domain": "tiandao"},
    "wangchangling":{"name": "王昌龄", "dynasty": "tang", "domain": "rendao"},
    "dumu":        {"name": "杜牧",   "dynasty": "tang", "domain": "shenmei"},
    "liuyuxi":     {"name": "刘禹锡", "dynasty": "tang", "domain": "xiushen"},
    "taoyuanming": {"name": "陶渊明", "dynasty": "jin",  "domain": "tiandao"},
    "sushi":       {"name": "苏轼",   "dynasty": "song", "domain": "xiushen", "person": "sushi"},
    "xinqiji":     {"name": "辛弃疾", "dynasty": "song", "domain": "zhidao"},
    "liqingzhao":  {"name": "李清照", "dynasty": "song", "domain": "shenmei"},
    "luyou":       {"name": "陆游",   "dynasty": "song", "domain": "rendao"},
    "liuyong":     {"name": "柳永",   "dynasty": "song", "domain": "shenmei"},
}

# 概念 -> 八维 domain(用于派生 poetry.domain)
CONCEPT_DOMAIN = {
    "dao": "tiandao", "tian": "tiandao", "wuwei": "tiandao", "ziran": "tiandao",
    "yinyang": "tiandao", "wuxing": "tiandao",
    "ren": "rendao", "li": "rendao", "yi": "rendao", "xin": "rendao", "shu": "rendao", "de": "rendao",
    "xiao": "jiadao",
    "junzi": "xiushen", "cheng": "xiushen", "jing": "xiushen", "zhiyong": "xiushen",
    "qian": "xiushen", "jintui": "xiushen", "qi": "xiushen", "shendu": "xiushen", "ti": "xiushen",
    "he": "chushi", "zhongyong": "chushi",
    "zhong": "zhidao", "wangdao": "zhidao", "badao": "zhidao", "minben": "zhidao",
    "lian": "zhidao", "deshi": "zhidao", "fazhi": "zhidao", "shi": "zhidao",
    "jingshi": "jingshi", "shishiqiushi": "jingshi",
}

# 关键词 -> 概念 slug(只取相对特异的哲学词,避免 道/天/民/诗 等泛词刷屏)
CONCEPT_KEYWORDS = [
    ("dao", ["大道"]), ("de", ["德"]), ("wuwei", ["无为"]), ("ziran", ["自然"]),
    ("yinyang", ["阴阳"]), ("wuxing", ["五行"]),
    ("ren", ["仁"]), ("li", ["礼"]), ("yi", ["义"]), ("xin", ["信"]), ("shu", ["恕"]),
    ("xiao", ["孝"]), ("junzi", ["君子"]), ("cheng", ["诚"]), ("jing", ["敬"]),
    ("zhiyong", ["智勇"]), ("qian", ["谦"]), ("jintui", ["进退"]), ("qi", ["气"]),
    ("shendu", ["慎独"]), ("ti", ["体"]),
    ("he", ["和"]), ("zhongyong", ["中庸"]), ("zhong", ["忠"]), ("wangdao", ["王道"]),
    ("badao", ["霸道"]), ("minben", ["民本"]), ("lian", ["廉"]), ("deshi", ["德治"]),
    ("fazhi", ["法治"]), ("shi", ["势"]), ("jingshi", ["经世", "济世"]),
    ("shishiqiushi", ["实事"]), ("shi4", ["诗言"]),
]


def fetch_raw(url: str):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 daokedao-importer"})
    try:
        with urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except HTTPError:
        return None  # 404 等:文件不存在,直接跳过不重试
    except Exception:
        time.sleep(1)
        try:
            with urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None


def match_concepts(text: str):
    """返回 (related_concepts[list], domain or None)"""
    found = []
    for concept, kws in CONCEPT_KEYWORDS:
        if any(kw in text for kw in kws):
            found.append(concept)
        if len(found) >= 3:
            break
    domain = None
    for c in found:
        if c in CONCEPT_DOMAIN:
            domain = CONCEPT_DOMAIN[c]
            break
    return found, domain


def collect():
    collected = {slug: [] for slug in CURATED}
    targets = {c["name"]: slug for slug, c in CURATED.items()}
    sources = [
        ("https://raw.githubusercontent.com/chinese-poetry/chinese-poetry/master/"
         + quote("全唐诗") + "/poet.tang.{}.json", "poem"),
        ("https://raw.githubusercontent.com/chinese-poetry/chinese-poetry/master/"
         + quote("全唐诗") + "/poet.song.{}.json", "poem"),
        ("https://raw.githubusercontent.com/chinese-poetry/chinese-poetry/master/"
         + quote("宋词") + "/ci.song.{}.json", "ci"),
    ]
    scanned = 0
    for url_template, kind in sources:
        if all(len(collected[s]) >= MAX_PER_POET for s in CURATED):
            break
        for i in range(0, MAX_FILES * 1000, 1000):
            if all(len(collected[s]) >= MAX_PER_POET for s in CURATED):
                break
            url = url_template.format(i)
            data = fetch_raw(url)
            scanned += 1
            if not isinstance(data, list):
                continue  # 跳过缺失文件,不中断整源扫描
            for p in data:
                a = HanziConv.toSimplified(p.get("author") or "")
                if a in targets:
                    slug = targets[a]
                    if len(collected[slug]) < MAX_PER_POET:
                        collected[slug].append((kind, p))
    return collected, scanned


def write_poet(slug, meta, poems):
    pdir = POETRY / slug
    pdir.mkdir(parents=True, exist_ok=True)
    era_note = {"tang": "唐代", "song": "宋代", "jin": "东晋"}.get(meta["dynasty"], meta["dynasty"])
    author_md = (
        f"---\nslug: {slug}\nname: {meta['name']}\ndynasty: {meta['dynasty']}\n"
        f"review_status: DRAFT\ncredibility_level: B\ncontributors:\n"
        f"  - id: yiwangxi-team\n    roles: [transcribe]\n    date: {TODAY}\n"
        f"---\n\n# {meta['name']}\n\n{era_note}诗人。"
        f"本条目由 chinese-poetry 数据集导入、繁简转换,待人工校勘与补传小传。\n"
    )
    (pdir / "author.md").write_text(author_md, encoding="utf-8")
    wdir = pdir / "works"
    wdir.mkdir(exist_ok=True)
    for idx, (kind, p) in enumerate(poems, 1):
        raw_title = p.get("title")
        title = HanziConv.toSimplified(raw_title).strip() if raw_title else ""
        if not title:
            title = HanziConv.toSimplified(p.get("rhythmic") or "").strip() or "（无题）"
        paras = [HanziConv.toSimplified(x).strip() for x in p.get("paragraphs", []) if x.strip()]
        if not paras:
            continue
        body = "\n".join(paras)
        concepts, domain = match_concepts(title + "\n" + body)
        if kind == "ci":
            genre = p.get("rhythmic") or "词"
        else:
            n = len(paras)
            genre = "绝句" if n == 4 else ("律诗" if n == 8 else "古诗")
        domain = domain or meta.get("domain")
        lines = [
            "---",
            f"slug: {slug}-{idx:03d}",
            f"poet_slug: {slug}",
            f"title: {title}",
            f"dynasty: {meta['dynasty']}",
            f"genre: {genre}",
        ]
        if domain:
            lines.append(f"domain: {domain}")
        if concepts:
            lines.append("related_concepts: [" + ", ".join(concepts) + "]")
        lines += [
            "text_source: chinese-poetry 数据集(公版) + 道可道繁简转换(hanziconv),待与权威版本校勘",
            "review_status: DRAFT",
            "credibility_level: B",
            "contributors:",
            "  - id: yiwangxi-team",
            "    roles: [transcribe]",
            f"    date: {TODAY}",
            "ai_used: hanziconv(繁简转换)",
            "---",
            "",
            "## 原文",
            "",
            body,
            "",
        ]
        (wdir / f"{slug}-{idx:03d}.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    dry = "--dry" in sys.argv
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--max-files="):
            MAX_FILES = int(a.split("=", 1)[1])
        elif a == "--max-files":
            MAX_FILES = int(args[i + 1]); i += 1
        elif a.startswith("--max-per-poet="):
            MAX_PER_POET = int(a.split("=", 1)[1])
        elif a == "--max-per-poet":
            MAX_PER_POET = int(args[i + 1]); i += 1
        i += 1
    collected, scanned = collect()
    total = sum(len(v) for v in collected.values())
    print(f"[scan] 扫描文件数={scanned}, 命中作品={total}")
    for slug, poems in collected.items():
        print(f"  {slug} ({CURATED[slug]['name']}): {len(poems)} 首")
    if dry or total == 0:
        return
    for slug, poems in collected.items():
        if poems:
            write_poet(slug, CURATED[slug], poems)
    print(f"[done] 已写入 {total} 首到 {POETRY}")


if __name__ == "__main__":
    main()
