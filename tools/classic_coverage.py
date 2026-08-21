#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
classic_coverage.py — 经典章节覆盖度统计（content-plan.md「需新建工具」）

用法:
    python tools/classic_coverage.py [--json]

统计每部经典:
    应有章节数  = classic.md frontmatter 的 chapter_count（未声明则按实际章节号最大值推断）
    已有章节数  = chapters/*.md 文件数（仅统计已解析成功且有 chapter_number 的）
    覆盖率      = 已有 / 应有

输出: 覆盖度表格（或 --json 输出机器可读 JSON）。
退出码: 0 = 正常统计（无论覆盖率高低）；1 = 运行/配置错误。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CONTENT_ROOT = Path(__file__).resolve().parent.parent


def parse_frontmatter(text: str) -> dict | None:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None
    fm: dict = {}
    for ln in lines[1:end]:
        if ":" not in ln:
            continue
        k, _, v = ln.partition(":")
        k, v = k.strip(), v.strip()
        if v.startswith("["):
            v = v[1:-1]
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        fm[k] = v
    return fm


def expected_count(classic_dir: Path, fm: dict) -> int | None:
    """应有章节数：优先 chapter_count，其次按已有章节号最大值。"""
    if fm and fm.get("chapter_count"):
        try:
            return int(fm["chapter_count"])
        except ValueError:
            pass
    nums = []
    for f in classic_dir.glob("chapters/*.md"):
        m = re.match(r"^(\d{3})-", f.name)
        if m:
            nums.append(int(m.group(1)))
    return max(nums) if nums else None


def scan() -> list[dict]:
    rows = []
    for classic_dir in sorted(CONTENT_ROOT.glob("classics/*")):
        meta = classic_dir / "classic.md"
        if not meta.exists():
            continue
        fm = parse_frontmatter(meta.read_text(encoding="utf-8"))
        slug = classic_dir.name
        title = (fm or {}).get("title", slug)
        have = 0
        for f in classic_dir.glob("chapters/*.md"):
            c_fm = parse_frontmatter(f.read_text(encoding="utf-8"))
            if c_fm and c_fm.get("chapter_number") is not None:
                have += 1
        want = expected_count(classic_dir, fm)
        pct = round(have / want * 100) if want else None
        rows.append({
            "slug": slug,
            "title": title,
            "expected": want,
            "actual": have,
            "coverage": pct,
        })
    return rows


def main() -> int:
    args = sys.argv[1:]
    as_json = "--json" in args
    rows = scan()
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    sys.stdout.reconfigure(encoding="utf-8")
    # 覆盖率合计：仅统计声明了 chapter_count 的经典（否则分母无意义）
    declared = [r for r in rows if r["expected"]]
    total_have = sum(r["actual"] for r in declared)
    total_want = sum(r["expected"] for r in declared)
    print(f"经典章节覆盖度 — root: {CONTENT_ROOT}")
    print(f"{'经典':<14}{'名称':<10}{'应有':>5}{'已有':>5}{'覆盖率':>8}")
    print("-" * 46)
    for r in rows:
        cov = f"{r['coverage']}%" if r["coverage"] is not None else "—"
        print(f"{r['slug']:<14}{r['title']:<10}{str(r['expected'] or '—'):>5}{r['actual']:>5}{cov:>8}")
    print("-" * 46)
    if total_want:
        print(f"已声明章节数的经典合计: {total_have}/{total_want} 章（{round(total_have / total_want * 100)}%）")
        print(f"全仓章节总数: {sum(r['actual'] for r in rows)} 章（{sum(1 for r in rows if r['actual'])} 部有章节）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
