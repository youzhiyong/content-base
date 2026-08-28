#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_tag_poem_classics.py —— 批量给诗词 frontmatter 补 related_classics（引用 26 部经典 slug）。

用法: python content/tools/_tag_poem_classics.py [--dry-run]
- 只处理 content/poetry/<poet>/works/*.md 中尚未有 related_classics 的诗词
- 限定从 CLASSIC_CATALOG 中选择，防 LLM 幻觉 slug；无效 slug 直接丢弃
- 保留已有 related_concepts 不动
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 26 部经典目录（slug: 中文名）——只允许从这里选
CLASSIC_CATALOG = {
    "shijing": "诗经", "daodejing": "道德经", "lunyu": "论语", "mengzi": "孟子",
    "zhuangzi": "庄子", "hanfeizi": "韩非子", "mozi": "墨子", "sunzibingfa": "孙子兵法",
    "zhongyong": "中庸", "daxue": "大学", "zhouyi": "周易", "shangshu": "尚书",
    "liji": "礼记", "chunqiu": "春秋", "shiji": "史记", "xinjing": "心经",
    "tanjing": "坛经", "taijitushuo": "太极图说", "shanghanlun": "伤寒论",
    "chuanxilu": "传习录", "jinsilu": "近思录", "rizhilu": "日知录",
    "shangjunshu": "商君书", "mingyidaifanglu": "名医类案", "sishuzhangjujizhu": "四书章句集注",
    "liezi": "列子",
}

KEY = re.search(r"DEEPSEEK_API_KEY=(sk-[0-9a-f]+)", (ROOT.parent / "backend" / ".env").read_text(encoding="utf-8")).group(1)
MODEL = "deepseek-chat"


def call(prompt: str, max_tokens: int = 2000) -> str:
    for attempt in range(4):
        budget = max_tokens * (2 ** attempt)
        data = json.dumps(
            {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": budget}
        )
        try:
            r = subprocess.run(
                ["curl", "-sS", "-X", "POST", "https://api.deepseek.com/v1/chat/completions",
                 "-H", f"Authorization: Bearer {KEY}", "-H", "Content-Type: application/json", "-d", data],
                capture_output=True, text=True, timeout=300,
            )
            j = json.loads(r.stdout)
            c = j["choices"][0]["message"]["content"].strip()
            if c:
                return c
            print(f"  [空内容 retry {attempt}]", file=sys.stderr)
        except Exception as e:
            print(f"  [异常 retry {attempt}] {e}", file=sys.stderr)
        time.sleep(4)
    return ""


def parse_tagged(text: str) -> dict:
    """解析 LLM 输出为 {poem_slug: [classic_slug...]}，容错提取 JSON 对象。"""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        raw = json.loads(m.group(0))
    except Exception:
        return {}
    out = {}
    for k, v in raw.items():
        if isinstance(v, list):
            valid = [x for x in v if x in CLASSIC_CATALOG]
            if valid:
                out[k] = valid
    return out


def read_frontmatter(path: pathlib.Path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None, text
    return m.group(1), text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch", type=int, default=10)
    args = parser.parse_args()

    works = sorted(ROOT.glob("poetry/*/works/*.md"))
    todo = []
    for w in works:
        fm, _ = read_frontmatter(w)
        if fm is None:
            continue
        if "related_classics" in fm:
            continue  # 已标注
        slug = re.search(r"^slug:\s*(\S+)", fm, re.M)
        title = re.search(r"^title:\s*(.+)", fm, re.M)
        poet = re.search(r"^poet_name:\s*(.+)", fm, re.M)
        if not slug:
            continue
        body = w.read_text(encoding="utf-8").split("## 原文")[-1].strip()
        first = "；".join([l.strip() for l in body.splitlines() if l.strip()][:3])[:120]
        todo.append({"path": w, "slug": slug.group(1), "title": title.group(1).strip() if title else "",
                     "poet": poet.group(1).strip() if poet else "", "first": first})

    print(f"待标注诗词: {len(todo)} 首（批 {args.batch} 首/次）")
    if args.dry_run:
        for t in todo[:5]:
            print(f"  {t['slug']} {t['poet']}《{t['title']}》 {t['first'][:40]}...")
        return

    catalog = "、".join(f"{slug}({name})" for slug, name in CLASSIC_CATALOG.items())
    changed = 0
    for i in range(0, len(todo), args.batch):
        chunk = todo[i:i + args.batch]
        items = "\n".join(
            f"- slug: {t['slug']} | 作者: {t['poet']} | 题: {t['title']} | 首句: {t['first']}"
            for t in chunk
        )
        prompt = (
            "你是国学文献学者。下面每首诗词需标注其思想渊源/文学传统最相关的经典，每首 0-2 部。\n"
            f"可选的经典 slug 目录(只能从这里选, 不得自造): {catalog}\n"
            "规则: 优先思想关联(儒家/道家/佛学/史传/政论), 其次文学传统(诗经风雅/乐府/骚体); "
            "关系弱或不确定则给空数组。\n"
            f"严格输出 JSON 对象: {{\"poem_slug\": [\"slug1\", ...], ...}}, 只输出 JSON。\n\n{items}"
        )
        text = call(prompt, max_tokens=2500)
        tagged = parse_tagged(text)
        for t in chunk:
            slugs = tagged.get(t["slug"], [])
            if not slugs:
                continue
            if args.dry_run:
                print(f"  {t['slug']} -> {slugs}")
                continue
            fm, text0 = read_frontmatter(t["path"])
            if fm is None:
                continue
            line = f"related_classics: [{', '.join(slugs)}]"
            new_fm = fm
            if "related_concepts:" in new_fm:
                new_fm = re.sub(r"(^related_concepts:.*$)", r"\1\n" + line, new_fm, flags=re.M)
            elif "text_source:" in new_fm:
                new_fm = re.sub(r"(^text_source:.*$)", line + r"\n\1", new_fm, flags=re.M)
            else:
                new_fm = new_fm + "\n" + line
            new_text = text0.replace(fm, new_fm, 1)
            t["path"].write_text(new_text, encoding="utf-8")
            changed += 1
            print(f"  [ok] {t['slug']} {t['poet']}《{t['title']}》 -> {slugs}")
        time.sleep(1)

    print(f"完成: 更新 {changed} 首")


if __name__ == "__main__":
    main()
