#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check.py — content/ 仓库内容校验器(零外部依赖,仅 Python 标准库)

用法:
    python tools/check.py [--seeds] [--verbose]

校验项:
  1. frontmatter 可解析(内置 YAML 子集解析器,无需 PyYAML)
  2. 按类型 schema 校验(自发现:扫描 schema/*.schema.json,README §4)
  3. slug 类型内唯一 + 命名规范([a-z0-9-],小写;跨类型同名合法,见 collect_slugs)
  4. 状态机硬约束(README §3.2):
     - C 级不可 PUBLISHED
     - ai_used 存在且无 contributors ⇒ 不允许离开 DRAFT
  5. AUTHORS.yaml 引用完整性(contributors/reviewers 的 id 必须已注册)
  6. 跨文件引用完整性(author_slug → persons、classic → classics)
  7. 经典章节正文:三区段结构 + 原文/今译编号对齐(程序渲染正确性的前提)
  8. --seeds:校验 data/seeds/{persons,classics}.json 与 schema 对齐(M2 拆库铺垫)

退出码:0 = 全部通过;1 = 有错误;2 = 运行/配置错误
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CONTENT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = CONTENT_ROOT / "schema"
AUTHORS_FILE = CONTENT_ROOT / "AUTHORS.yaml"

# ---------------------------------------------------------------------------
# 1. frontmatter + YAML 子集解析器
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> tuple[dict | None, str]:
    """解析 '---\\n...\\n---' 围栏。返回 (frontmatter dict, 正文)。"""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ValueError("frontmatter 围栏未闭合(缺少结束 ---)")
    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    data = parse_yaml_subset(fm_text)
    if not isinstance(data, dict):
        raise ValueError("frontmatter 顶层必须是键值对(YAML 映射)")
    return data, body


def _strip_inline_comment(s: str) -> str:
    """去掉行内注释(# 后跟空格的视为注释)。"""
    out, i, quote = [], 0, None
    while i < len(s):
        ch = s[i]
        if quote:
            out.append(ch)
            if ch == quote and (i == 0 or s[i - 1] != "\\"):
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or s[i - 1] == " "):
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _parse_inline_array(s: str) -> list:
    """解析内联数组 [a, b, c]。"""
    s = s.strip()
    assert s.startswith("[") and s.endswith("]"), f"非法内联数组: {s}"
    inner = s[1:-1].strip()
    if not inner:
        return []
    items, buf, quote, depth = [], "", None, 0
    for ch in inner:
        if quote:
            buf += ch
            if ch == quote and buf[-2:-1] != "\\":
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf += ch
        elif ch == "[":
            depth += 1
            buf += ch
        elif ch == "]":
            depth -= 1
            buf += ch
        elif ch == "," and depth == 0:
            items.append(_parse_scalar(buf.strip()))
            buf = ""
        else:
            buf += ch
    if buf.strip():
        items.append(_parse_scalar(buf.strip()))
    return items


def _parse_scalar(s: str):
    """解析标量:引号字符串 / null / bool / int / 普通字符串。"""
    s = s.strip()
    if not s:
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        inner = s[1:-1]
        return inner.replace('\\"', '"').replace("\\'", "'")
    if s in ("null", "Null", "NULL", "~"):
        return None
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return s


def parse_yaml_subset(text: str) -> object:
    """解析 frontmatter 所需的最小 YAML 子集(映射 / 序列 / 标量)。"""
    lines = [ln.rstrip("\n") for ln in text.split("\n")]
    value, _ = _parse_block(lines, 0, 0)
    return value


def _indent_of(line: str) -> tuple[int, str]:
    raw = line.replace("\t", "  ")
    stripped = raw.lstrip(" ")
    return len(raw) - len(stripped), stripped


def _parse_block(lines: list[str], idx: int, indent: int):
    """递归解析块。返回 (解析值, 下一个未消费行号)。

    支持:
      key: value           标量映射
      key: [a, b]          内联数组
      key:                 空值 / 子块(下一行缩进更深)
      - item               序列(标量或映射)
      - key: value         序列中的映射(首行即属性,后续行是其余属性)
    """
    if idx >= len(lines):
        return None, idx
    first_indent, first = _indent_of(lines[idx])
    if first_indent < indent or first == "" or first.startswith("#"):
        return None, idx

    # 序列
    if first.startswith("- "):
        items, i = [], idx
        while i < len(lines):
            cur_indent, cur = _indent_of(lines[i])
            if cur_indent != first_indent or not cur.startswith("- "):
                break
            rest = cur[2:].strip()
            if not rest or rest.startswith("#"):
                items.append(None)
                i += 1
                continue
            if ":" in rest and not rest.startswith(("'", '"')):
                # 序列项是映射: - key: value 或 - key:
                key, _, val = rest.partition(":")
                key, val = key.strip(), val.strip()
                item = {}
                if val:
                    item[_parse_scalar(key)] = _parse_scalar(val) if not val.startswith("[") else _parse_inline_array(val)
                else:
                    item[_parse_scalar(key)] = None
                # 收集后续缩进更深的属性行
                j = i + 1
                while j < len(lines):
                    n_indent, n_line = _indent_of(lines[j])
                    if n_line == "" or n_line.startswith("#") or n_indent <= first_indent:
                        break
                    if n_line.startswith("- "):
                        break
                    k, _, v = n_line.partition(":")
                    k, v = k.strip(), v.strip()
                    if v.startswith("["):
                        item[_parse_scalar(k)] = _parse_inline_array(v)
                        j += 1
                    elif v == "":
                        sub, nxt = _parse_block(lines, j + 1, n_indent + 1)
                        item[_parse_scalar(k)] = sub
                        j = nxt
                    else:
                        item[_parse_scalar(k)] = _parse_scalar(v)
                        j += 1
                items.append(item)
                i = j
            else:
                items.append(_parse_scalar(rest))
                i += 1
        return items, i

    # 映射
    mapping, i = {}, idx
    while i < len(lines):
        cur_indent, cur = _indent_of(lines[i])
        if cur_indent != first_indent or cur == "" or cur.startswith("#"):
            break
        if ":" not in cur:
            break
        key, _, val = cur.partition(":")
        key, val = key.strip(), val.strip()
        if not key:
            break
        if val.startswith("["):
            mapping[_parse_scalar(key)] = _parse_inline_array(val)
            i += 1
        elif val:
            mapping[_parse_scalar(key)] = _parse_scalar(val)
            i += 1
        else:
            # 空值:看下一行是否缩进更深 → 子块
            nxt = i + 1
            if nxt < len(lines):
                n_indent, n_line = _indent_of(lines[nxt])
                if n_line and not n_line.startswith("#") and n_indent > cur_indent:
                    sub, nxt = _parse_block(lines, nxt, n_indent)
                    mapping[_parse_scalar(key)] = sub
                else:
                    mapping[_parse_scalar(key)] = None
            else:
                mapping[_parse_scalar(key)] = None
            i = nxt
    return mapping, i


# ---------------------------------------------------------------------------
# 2. JSON Schema 子集校验器($ref 合并 _common)
# ---------------------------------------------------------------------------


class SchemaError(Exception):
    pass


def _resolve_ref(schema: dict, base_dir: Path) -> dict:
    """解析 $ref(仅支持本地 .json 相对引用),合并进当前 schema。"""
    ref = schema.get("$ref")
    if not ref:
        return schema
    target = base_dir / ref.lstrip("./")
    if not target.exists():
        raise SchemaError(f"schema $ref 不存在: {target}")
    merged = json.loads(target.read_text(encoding="utf-8"))
    merged.pop("$schema", None)
    merged.pop("$id", None)
    merged.pop("title", None)
    merged.pop("description", None)
    merged.pop("$ref", None)
    # 合并 properties / required(当前 schema 优先)
    for k in ("properties", "required"):
        mine = schema.get(k)
        if isinstance(mine, dict):
            merged.setdefault(k, {})
            merged[k].update(mine)
        elif isinstance(mine, list):
            merged.setdefault(k, [])
            merged[k] = mine + [x for x in merged[k] if x not in mine]
    merged.pop("allOf", None)
    return merged


def _check_value(value, schema: dict, path: str, base_dir: Path, errors: list[str]):
    if "$ref" in schema:
        schema = _resolve_ref(schema, base_dir)
    schema.pop("$ref", None)

    typ = schema.get("type")
    if isinstance(typ, list):
        if not any(_type_ok(value, t) for t in typ):
            errors.append(f"{path}: 类型应为 {'/'.join(typ)},实际 {type(value).__name__}")
    elif typ and not _type_ok(value, typ):
        errors.append(f"{path}: 类型应为 {typ},实际 {type(value).__name__} = {value!r}")

    if isinstance(value, str):
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            errors.append(f"{path}: 不匹配 pattern {schema['pattern']!r} = {value!r}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: 长度不足 minLength={schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: 超出 maxLength={schema['maxLength']}")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: 小于 minimum={schema['minimum']}")

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 值 {value!r} 不在枚举 {schema['enum']}")

    if isinstance(value, dict):
        if "required" in schema:
            for r in schema["required"]:
                if r not in value:
                    errors.append(f"{path}: 缺少必填字段 {r!r}")
        for k, sub in (schema.get("properties") or {}).items():
            if k in value:
                _check_value(value[k], sub, f"{path}.{k}", base_dir, errors)
    elif isinstance(value, list):
        if "items" in schema:
            for i, item in enumerate(value):
                _check_value(item, schema["items"], f"{path}[{i}]", base_dir, errors)


def _type_ok(value, t: str) -> bool:
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "array":
        return isinstance(value, list)
    if t == "object":
        return isinstance(value, dict)
    if t == "null":
        return value is None
    return True


def validate_schema(data: dict, schema_file: Path) -> list[str]:
    """按 schema 文件校验 dict。返回错误列表(空 = 通过)。"""
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    errors: list[str] = []
    base_dir = schema_file.parent
    _check_value(data, schema, schema_file.stem, base_dir, errors)
    return errors


# ---------------------------------------------------------------------------
# 3. 类型注册表(目录 = 类型,check.py 的扫描规则)
# ---------------------------------------------------------------------------

# type_key -> (目录模式, schema 文件名, 是否要求 slug)
TYPE_RULES = {
    "classic": {
        "glob": "classics/*/classic.md",
        "schema": "classic.schema.json",
    },
    "classic-chapter": {
        "glob": "classics/*/chapters/*.md",
        "schema": "classic-chapter.schema.json",
    },
    "person": {
        "glob": "entities/persons/*.md",
        "schema": "person.schema.json",
    },
    "concept": {
        "glob": "entities/concepts/*.md",
        "schema": "concept.schema.json",
    },
    "poetry": {
        "glob": "poetry/*/works/*.md",
        "schema": "poetry.schema.json",
    },
}


def discover_types() -> list[str]:
    """自发现:列出 schema/ 下已注册的类型(目录未建也算注册)。"""
    return sorted(t for t in TYPE_RULES if (SCHEMA_DIR / TYPE_RULES[t]["schema"]).exists())


# ---------------------------------------------------------------------------
# 4. 校验逻辑
# ---------------------------------------------------------------------------


class Reporter:
    def __init__(self, verbose: bool):
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.verbose = verbose
        self.checked = 0

    def ok(self, msg: str):
        self.checked += 1
        if self.verbose:
            print(f"  ✓ {msg}")

    def err(self, msg: str):
        self.errors.append(msg)
        print(f"  ✗ {msg}")

    def warn(self, msg: str):
        self.warnings.append(msg)
        print(f"  ⚠ {msg}")


def extract_authors(rep: Reporter) -> set[str]:
    """从 AUTHORS.yaml 提取注册 ID:剔除代码块与 HTML 注释后,匹配 '- id: xxx'。"""
    if not AUTHORS_FILE.exists():
        rep.warn("AUTHORS.yaml 不存在,跳过署名引用校验")
        return set()
    text = AUTHORS_FILE.read_text(encoding="utf-8")
    text = re.sub(r"```yaml.*?```", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    ids = set(re.findall(r"^\s*- id:\s*(\S+)\s*$", text, flags=re.M))
    return ids


def check_state_machine(fm: dict, rel: str, rep: Reporter):
    status = fm.get("review_status")
    level = fm.get("credibility_level", "B")
    if level == "C" and status == "PUBLISHED":
        rep.err(f"{rel}: 状态机硬约束——credibility_level=C 不可 PUBLISHED")
    ai = fm.get("ai_used")
    contributors = fm.get("contributors") or []
    if ai and not contributors and status and status != "DRAFT":
        rep.err(f"{rel}: 状态机硬约束——存在 ai_used 但无 contributors,不允许离开 DRAFT")


def check_authors_refs(fm: dict, rel: str, authors: set[str], rep: Reporter):
    for field in ("contributors", "reviewers"):
        for item in fm.get(field) or []:
            aid = item.get("id") if isinstance(item, dict) else None
            if aid and aid not in authors:
                rep.err(f"{rel}: {field} 引用了未注册的 AUTHORS ID: {aid!r}")


def check_chapter_body(body: str, rel: str, rep: Reporter):
    """章节正文:三区段结构 + 原文/今译编号对齐。"""
    sections: dict[str, str] = {}
    cur = None
    for line in body.split("\n"):
        m = re.match(r"^##\s*(原文|今译|注释)\s*$", line.strip())
        if m:
            cur = m.group(1)
            sections[cur] = []
        elif cur is not None:
            sections[cur].append(line)

    for name in ("原文", "今译", "注释"):
        if name not in sections:
            if name == "原文":
                rep.err(f"{rel}: 缺少 [## 原文] 区段(必填)")
            else:
                rep.warn(f"{rel}: 缺少 [## {name}] 区段(可选)")

    def numbers(sec_lines: list[str]) -> list[str]:
        nums = []
        for ln in sec_lines:
            for m in re.finditer(r"【(\d+\.\d+)】", ln):
                nums.append(m.group(1))
        return nums

    orig = numbers(sections.get("原文", []))
    trans = numbers(sections.get("今译", []))
    if not orig:
        return  # 原文缺失已在上面报错

    # 编号必须连续递增(1.1, 1.2, 1.3 …)
    for i, n in enumerate(orig, start=1):
        if n != f"{orig[0].split('.')[0]}.{i}":
            rep.err(f"{rel}: 原文编号不连续——第 {i} 条应为 【{orig[0].split('.')[0]}.{i}】,实际 【{n}】")
            break

    if trans and orig != trans:
        only_orig = set(orig) - set(trans)
        only_trans = set(trans) - set(orig)
        if only_orig:
            rep.err(f"{rel}: 今译缺少编号 {sorted(only_orig)}")
        if only_trans:
            rep.err(f"{rel}: 今译出现原文没有的编号 {sorted(only_trans)}")
    if orig and not trans and len(sections.get("今译", [])) == 0:
        rep.warn(f"{rel}: 有原文但无今译区段(译文策略未定,允许)")


# ---------------------------------------------------------------------------
# 5. 主流程
# ---------------------------------------------------------------------------


def collect_slugs(rep: Reporter) -> dict[str, dict[str, str]]:
    """扫描所有类型文件,收集 类型→{slug→相对路径}。slug 在**类型内**唯一。

    注意:slug 不要求全局唯一——人物与经典可能同名(如「孟子」既是人也是书),
    而所有跨文件引用(author_slug→persons、classic→classics 等)都是按类型作用域的,
    且产品 URL 也按类型命名空间(/persons/x vs /classics/x),故类型内唯一即可。
    """
    by_type: dict[str, dict[str, str]] = {}
    for tkey, rule in TYPE_RULES.items():
        schema_file = SCHEMA_DIR / rule["schema"]
        if not schema_file.exists():
            continue
        by_type[tkey] = {}
        for f in sorted(CONTENT_ROOT.glob(rule["glob"])):
            rel = f.relative_to(CONTENT_ROOT).as_posix()
            try:
                fm, body = parse_frontmatter(f.read_text(encoding="utf-8"))
            except ValueError as e:
                rep.err(f"{rel}: frontmatter 解析失败——{e}")
                continue
            if fm is None:
                rep.err(f"{rel}: 缺少 frontmatter 围栏(---)")
                continue
            # schema 校验(含 _common 合并)
            for e in validate_schema(fm, schema_file):
                rep.err(f"{rel}: {e}")
            slug = fm.get("slug")
            if slug:
                if slug in by_type[tkey]:
                    rep.err(f"{rel}: slug {slug!r} 与 {by_type[tkey][slug]} 重复(类型内唯一)")
                else:
                    by_type[tkey][slug] = rel
            rep.ok(f"{tkey}: {rel}")
    return by_type


def check_chapter_filenames(rep: Reporter):
    """章节文件名 {NNN}-{name}.md 与 chapter_number 一致性。"""
    for f in sorted(CONTENT_ROOT.glob("classics/*/chapters/*.md")):
        rel = f.relative_to(CONTENT_ROOT).as_posix()
        m = re.match(r"^(\d{3})", f.name)
        if not m:
            rep.err(f"{rel}: 章节文件名必须以三位编号开头(如 001-xueer.md 或 001.md)")
            continue
        try:
            fm, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if fm and fm.get("chapter_number") is not None:
            if int(m.group(1)) != int(fm["chapter_number"]):
                rep.err(f"{rel}: 文件名前缀 {m.group(1)} 与 chapter_number={fm['chapter_number']} 不一致")


def check_cross_refs(slugs: dict[str, str], rep: Reporter):
    """跨文件引用完整性:author_slug→persons,classic→classics。"""
    persons = {p.stem for p in CONTENT_ROOT.glob("entities/persons/*.md")}
    classics = {p.parent.name for p in CONTENT_ROOT.glob("classics/*/classic.md")}
    for f in sorted(CONTENT_ROOT.glob("classics/*/classic.md")):
        rel = f.relative_to(CONTENT_ROOT).as_posix()
        fm, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
        if not fm:
            continue
        author = fm.get("author_slug")
        if author and author not in persons:
            rep.err(f"{rel}: author_slug={author!r} 不存在于 entities/persons/")
    for f in sorted(CONTENT_ROOT.glob("classics/*/chapters/*.md")):
        rel = f.relative_to(CONTENT_ROOT).as_posix()
        fm, body = parse_frontmatter(f.read_text(encoding="utf-8"))
        if not fm:
            continue
        c = fm.get("classic")
        if c and c not in classics:
            rep.err(f"{rel}: classic={c!r} 不存在于 classics/")
        check_chapter_body(body, rel, rep)


def check_seeds(rep: Reporter) -> int:
    """--seeds:校验 data/seeds/*.json 与 schema 对齐。

    注:事实层(persons/classics/concepts)权威源已迁至 content/ 仓库(M2 拆库),
    data/seeds 仅保留变量层种子;当前变量层文件均无对应 schema,校验暂空,
    待新增 schema 后在此登记(如 events.json + event.schema.json)。
    """
    # 兼容两处: 主仓库 ../data/seeds (首选), 独立仓库自包含 seeds/ (候选)
    seeds_dir = CONTENT_ROOT.parent / "data" / "seeds"
    if not seeds_dir.exists():
        seeds_dir = CONTENT_ROOT / "seeds"
    if not seeds_dir.exists():
        rep.warn("data/seeds/ 不存在,跳过 seeds 校验")
        return 0
    # (文件名, schema 名);变量层种子暂无 schema,先留空
    pairs: list[tuple[str, str]] = []
    n = 0
    for fname, schema_name in pairs:
        fp = seeds_dir / fname
        if not fp.exists():
            rep.warn(f"data/seeds/{fname} 不存在,跳过")
            continue
        data = json.loads(fp.read_text(encoding="utf-8"))
        schema_file = SCHEMA_DIR / schema_name
        seen: set[str] = set()
        for item in data:
            slug = item.get("slug", "?")
            n += 1
            # 宽松模式:只做字段类型/枚举/pattern 校验,不要求 review_status(数据层无此字段)
            schema = json.loads(schema_file.read_text(encoding="utf-8"))
            schema["required"] = []
            errors: list[str] = []
            base_dir = schema_file.parent
            _check_value(item, schema, f"{fname}#{slug}", base_dir, errors)
            for e in errors:
                rep.err(e)
            if slug in seen:
                rep.err(f"{fname}: slug {slug!r} 重复")
            seen.add(slug)
            if not re.fullmatch(r"[a-z0-9-]+", str(slug)):
                rep.err(f"{fname}#{slug}: slug 命名违规(仅 [a-z0-9-])")
        rep.ok(f"seeds {fname}: {len(data)} 条字段校验完成")
    return n


def main() -> int:
    args = sys.argv[1:]
    seeds_mode = "--seeds" in args
    verbose = "--verbose" in args

    sys.stdout.reconfigure(encoding="utf-8")
    rep = Reporter(verbose)

    print(f"content/ 仓库校验器 — root: {CONTENT_ROOT}")
    print(f"已注册类型(自发现): {discover_types() or '(无)'}\n")

    authors = extract_authors(rep)
    if authors:
        print(f"AUTHORS 注册表: {len(authors)} 人\n")

    slugs = collect_slugs(rep)
    print()
    check_chapter_filenames(rep)
    check_cross_refs(slugs, rep)

    # 状态机 + AUTHORS 引用(对每个文件再走一遍,保持报错路径清晰)
    for tkey, rule in TYPE_RULES.items():
        if not (SCHEMA_DIR / rule["schema"]).exists():
            continue
        for f in sorted(CONTENT_ROOT.glob(rule["glob"])):
            rel = f.relative_to(CONTENT_ROOT).as_posix()
            try:
                fm, body = parse_frontmatter(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if not fm:
                continue
            check_state_machine(fm, rel, rep)
            check_authors_refs(fm, rel, authors, rep)

    print()
    if seeds_mode:
        check_seeds(rep)

    print(f"\n===== 结果: 文件/记录 {rep.checked} 个, 错误 {len(rep.errors)}, 警告 {len(rep.warnings)} =====")
    if rep.errors:
        print("❌ 校验失败:存在错误,不能合并")
        return 1
    if rep.warnings:
        print("⚠️ 通过,但有警告(可合并,建议处理)")
    else:
        print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
