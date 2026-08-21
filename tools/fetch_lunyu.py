#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_lunyu.py —— 从维基文库抓取《论语》20 篇公版原文, 转简体, 生成 content 章节文件。

来源: 维基文库《论语》全文 (公有领域, 作者逝世逾百年且 1931 年前出版)
      https://zh.wikisource.org/wiki/論語
格式: 维基文库 raw wikitext (<onlyinclude> 块内, 每章以 <div id="X之Y"> 标记)

输出: content/classics/lunyu/chapters/{NNN}-{pinyin}.md
      一篇一文件, frontmatter(classic/chapter_number/chapter_title/状态/署名/溯源) + ## 原文 段。
      今译/注释留空(加工层, 后续 AI/共创补全; check.py 允许多 warn)。

依赖: opencc (venv, 仅用于一次性生产; 运行时 check.py/sync.py 仍零依赖)
      curl (系统, 联网抓取 raw)
用法: python tools/fetch_lunyu.py
"""
import re
import subprocess
import sys
from pathlib import Path

try:
    import opencc
except ImportError:
    sys.exit("缺少 opencc, 请先: venv/Scripts/pip.exe install opencc")

CC = opencc.OpenCC("t2s")  # 繁 -> 简

CONTENT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = CONTENT_ROOT / "classics" / "lunyu" / "chapters"
OUT_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (compatible; YiwangxiContentBot/1.0; +https://github.com/yiwangxi)"
BASE = "https://zh.wikisource.org/wiki/%E8%AB%96%E8%AA%9E/"

# (篇号, 简体篇名, 拼音文件名, 维基文库繁体 slug 的 % 编码后缀)
BOOKS = [
    (1,  "学而第一",   "xueer",       "%E5%AD%B8%E8%80%8C%E7%AC%AC%E4%B8%80"),
    (2,  "为政第二",   "weizheng",    "%E7%88%B2%E6%94%BF%E7%AC%AC%E4%BA%8C"),
    (3,  "八佾第三",   "bayi",        "%E5%85%AB%E4%BD%BE%E7%AC%AC%E4%B8%89"),
    (4,  "里仁第四",   "liren",       "%E9%87%8C%E4%BB%81%E7%AC%AC%E5%9B%9B"),
    (5,  "公冶长第五", "gongyechang", "%E5%85%AC%E5%86%B6%E9%95%B7%E7%AC%AC%E4%BA%94"),
    (6,  "雍也第六",   "yongye",      "%E9%9B%8D%E4%B9%9F%E7%AC%AC%E5%85%AD"),
    (7,  "述而第七",   "shuer",       "%E8%BF%B0%E8%80%8C%E7%AC%AC%E4%B8%83"),
    (8,  "泰伯第八",   "taibo",       "%E6%B3%B0%E4%BC%AF%E7%AC%AC%E5%85%AB"),
    (9,  "子罕第九",   "zihan",       "%E5%AD%90%E7%BD%95%E7%AC%AC%E4%B9%9D"),
    (10, "乡党第十",   "xiangdang",   "%E9%84%89%E9%BB%A8%E7%AC%AC%E5%8D%81"),
    (11, "先进第十一", "xianjin",     "%E5%85%88%E9%80%B2%E7%AC%AC%E5%8D%81%E4%B8%80"),
    (12, "颜渊第十二", "yanyuan",     "%E9%A1%8F%E6%B7%B5%E7%AC%AC%E5%8D%81%E4%BA%8C"),
    (13, "子路第十三", "zilu",        "%E5%AD%90%E8%B7%AF%E7%AC%AC%E5%8D%81%E4%B8%89"),
    (14, "宪问第十四", "xianwen",     "%E6%86%B2%E5%95%8F%E7%AC%AC%E5%8D%81%E5%9B%9B"),
    (15, "卫灵公第十五", "weilinggong", "%E8%A1%9E%E9%9D%88%E5%85%AC%E7%AC%AC%E5%8D%81%E4%BA%94"),
    (16, "季氏第十六", "jishi",       "%E5%AD%A3%E6%B0%8F%E7%AC%AC%E5%8D%81%E5%85%AD"),
    (17, "阳货第十七", "yanghuo",     "%E9%99%BD%E8%B2%A8%E7%AC%AC%E5%8D%81%E4%B8%83"),
    (18, "微子第十八", "weizi",       "%E5%BE%AE%E5%AD%90%E7%AC%AC%E5%8D%81%E5%85%AB"),
    (19, "子张第十九", "zizhang",     "%E5%AD%90%E5%BC%B5%E7%AC%AC%E5%8D%81%E4%B9%9D"),
    (20, "尧曰第二十", "yaoyue",      "%E5%A0%AF%E6%9B%B0%E7%AC%AC%E4%BA%8C%E5%8D%81"),
]

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}


def cn2int(s: str) -> int:
    """中文数字转阿拉伯: 支持 一..九十九 (篇号 1-20, 章号 1-约44)。

    兼容维基文库两种写法: 有"十"(二十一) 与 无"十"(二一, 二十一章起常用)。
    """
    total, cur = 0, 0
    for ch in s:
        if ch in _CN_DIGITS:
            cur = cur * 10 + _CN_DIGITS[ch]
        elif ch == "十":
            total += (cur if cur else 1) * 10
            cur = 0
        elif ch == "百":
            total += (cur if cur else 1) * 100
            cur = 0
    return total + cur


def fetch_raw(slug_suffix: str) -> str:
    url = BASE + slug_suffix + "?action=raw"
    r = subprocess.run(["curl", "-sL", "--max-time", "40", "-A", UA, url],
                       capture_output=True, text=True)
    return r.stdout


def clean_body(raw: str) -> str:
    m = re.search(r"<onlyinclude>(.*?)</onlyinclude>", raw, re.S)
    body = m.group(1) if m else raw

    def repl_div(md):
        inner = md.group(1)            # 如 "一之一"
        if "之" in inner:
            p, c = inner.split("之", 1)
            try:
                return f"【{cn2int(p)}.{cn2int(c)}】"
            except Exception:
                return "【?】"
        return "【?】"

    # 章标记 <div id="..">'''X之Y'''</div> -> 【篇.章】
    body = re.sub(r"<div id=\"[^\"]*\"[^>]*>'''([^']*?)'''</div>", repl_div, body)
    # 异文模板 {{另2|A|B}} / {{另|A|B}} -> 取主校本 A
    body = re.sub(r"\{\{[^|{}]*\|([^}|]*)\|[^}]*\}\}", r"\1", body)
    body = re.sub(r"\{\{[^}|]*\|([^}]*)\}\}", r"\1", body)
    # 链接 [[a|b]] -> b ; [[a]] -> a
    body = re.sub(r"\[\[([^\[\]|]*)\|([^\[\]]*)\]\]", r"\2", body)
    body = re.sub(r"\[\[([^\[\]]*)\]\]", r"\1", body)
    # 语言变体 -{...}-
    body = re.sub(r"-\{[^}]*-\}", "", body)
    # 去加粗 / 剩余 HTML / 剩余模板
    body = body.replace("'''", "")
    body = re.sub(r"<[^>]+>", "", body)
    body = re.sub(r"\{\{[^}]*\}\}", "", body)
    # 清理空白行
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    return "\n".join(lines)


def main():
    total_chapters = 0
    for num, title, pinyin, slug in BOOKS:
        raw = fetch_raw(slug)
        if not raw or "<onlyinclude>" not in raw:
            print(f"  [跳过] 第{num}篇 {title}: 抓取失败/空 (len={len(raw)})", file=sys.stderr)
            continue
        body = clean_body(raw)
        body = CC.convert(body)  # 转简体
        # 统计章数
        chaps = len(re.findall(r"【\d+\.\d+】", body))
        total_chapters += chaps
        front = (
            "---\n"
            f"classic: lunyu\n"
            f"chapter_number: {num}\n"
            f"chapter_title: {title}\n"
            "review_status: PUBLISHED\n"
            "credibility_level: S\n"
            "contributors:\n"
            "  - id: yiwangxi-team\n"
            "    roles: [transcribe]\n"
            "    date: 2026-08-14\n"
            "text_source: 维基文库《论语》全文(公有领域; 底本为繁体, 本文件经 opencc 转简体), "
            "https://zh.wikisource.org/wiki/論語\n"
            "---\n\n"
            "## 原文\n\n"
            f"{body}\n"
        )
        out = OUT_DIR / f"{num:03d}-{pinyin}.md"
        out.write_text(front, encoding="utf-8")
        print(f"  [生成] {out.name}: 篇《{title}》 {chaps} 章")
    print(f"完成: 20 篇, 共 {total_chapters} 章原文入库 content/classics/lunyu/chapters/")


if __name__ == "__main__":
    main()
