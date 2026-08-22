#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_events.py — 把 data/seeds/events.json 的 30 条事件批转为 content/events/*.md

一次性迁移脚本(跑完即弃,不纳入日常流程)。
字段映射: slug/title/era_slug/year/summary/significance 原样搬;
补 review_status=PUBLISHED + credibility_level=A + contributors(yiwangxi-team)。
正文留空(## 详述 区段二期再接 events.description)。

用法:
    python scripts/convert_events.py [--dry-run]
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "seeds" / "events.json"
OUT_DIR = ROOT / "content" / "events"
TODAY = date.today().isoformat()

# 现有 30 条来自 DataSeeder 已置 PUBLISHED,此处直接继承可信度 A。
CONTRIB_ID = "yiwangxi-team"


def to_markdown(ev: dict) -> str:
    slug = ev["slug"]
    title = ev["title"]
    era = ev.get("era_slug") or ""
    year = ev.get("year")
    summary = ev.get("summary") or ""
    significance = ev.get("significance") or ""

    lines = [
        "---",
        f"slug: {slug}",
        f"title: {title}",
        f"era_slug: {era}",
        f"year: {year}",
        f"summary: {summary}",
        f"significance: {significance}",
        "review_status: PUBLISHED",
        "credibility_level: A",
        "contributors:",
        f"  - id: {CONTRIB_ID}",
        "    roles:",
        "      - collate",
        f"    date: {TODAY}",
        "---",
        "",
        f"# {title}",
        "",
        summary,
        "",
        "> 历史意义:" + significance,
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not SEED.exists():
        print(f"[ERR] 找不到 {SEED}", file=sys.stderr)
        return 2

    events = json.loads(SEED.read_text(encoding="utf-8"))
    print(f"读取 {SEED.name}: {len(events)} 条")

    if not args.dry_run:
        OUT_DIR.mkdir(parents=True, exist_ok=True)

    written = 0
    for ev in events:
        md = to_markdown(ev)
        fname = f"{ev['slug']}.md"
        if args.dry_run:
            print(f"  ~ 将写 content/events/{fname} ({len(md)}B)")
        else:
            (OUT_DIR / fname).write_text(md, encoding="utf-8")
            print(f"  + content/events/{fname}")
        written += 1

    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}批转完成: {written} 个事件 md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
