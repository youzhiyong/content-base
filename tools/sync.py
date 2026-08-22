#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync.py — content/ 仓库增量同步到 DB 事实表(零外部依赖,仅 Python 标准库 + psql)

用法:
    python tools/sync.py [--dry-run] [--verbose] [--psql-cmd "docker exec ..."]

流程(README §7 / 设计文档 docs/content-sync-design.md):
  1. 扫描 content/ 所有 .md,算 sha256 内容 hash
  2. 查 content_sync_state(幂等锚点),hash 不变 → 跳过
  3. 变化的文件:复用 check.py 校验(schema + 状态机 + AUTHORS 引用)
  4. 校验通过 → upsert 事实表(persons / classics / classic_chapters)
  5. 更新 content_sync_state(path → hash + synced_at)
  6. 删除检测:sync_state 有记录但文件已不存在 → 标记 + 提示
  7. 输出受影响 slug(供派生层:图谱 / 卡片 / embeddings 重算)

设计要点:
  - 幂等:内容 hash 不变就不碰 DB,天然去重
  - 安全 upsert:ON CONFLICT 只更新 frontmatter 中出现的字段,未出现的列保持原值
  - 事务:所有 upsert 在单个 BEGIN…COMMIT 中,中途失败全回滚
  - 失败隔离:单文件校验/解析失败只跳过,不阻塞整批
  - 零依赖:不用 psycopg2,通过 psql subprocess 交互;开源仓库可直接跑

退出码:0 = 成功;1 = 有校验错误(部分文件被跳过);2 = 运行/DB 错误
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
import shlex
import subprocess
import sys
from pathlib import Path

# 复用 check.py 的解析器与校验函数
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check import (  # noqa: E402
    parse_frontmatter,
    TYPE_RULES,
    CONTENT_ROOT,
    SCHEMA_DIR,
    validate_schema,
    extract_authors,
)

DEFAULT_PSQL_CMD = "docker exec -i yiwangxi-postgres psql -U yiwangxi -d yiwangxi"

SYNC_STATE_DDL = """\
CREATE TABLE IF NOT EXISTS content_sync_state (
    path          TEXT PRIMARY KEY,
    content_hash  TEXT NOT NULL,
    entity_type   TEXT,
    slug          TEXT,
    synced_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status        TEXT NOT NULL DEFAULT 'ok',
    error         TEXT
);\
"""


# ---------------------------------------------------------------------------
# DB 层(psql subprocess,零依赖)
# ---------------------------------------------------------------------------


class Db:
    """通过 psql subprocess 与 PostgreSQL 交互。"""

    def __init__(self, cmd_str: str, verbose: bool = False):
        self.cmd = shlex.split(cmd_str)
        self.verbose = verbose

    def _run(self, sql: str, extra_args: list[str] | None = None) -> str:
        args = self.cmd + (extra_args or []) + ["-v", "ON_ERROR_STOP=1"]
        if self.verbose:
            preview = sql.replace("\n", " ")[:100]
            print(f"  [psql] <<{len(sql)}B>> {preview}...")
        r = subprocess.run(
            args,
            input=sql,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if r.returncode != 0:
            raise RuntimeError(f"psql 错误:\n{r.stderr.strip()}")
        return r.stdout

    def query(self, sql: str) -> list[list[str]]:
        """查询,返回行列表(每行按 tab 分割)。"""
        out = self._run(sql, ["-t", "-A", "-F", "\t"])
        return [line.split("\t") for line in out.strip().split("\n") if line]

    def execute(self, sql: str) -> str:
        """执行写操作。"""
        return self._run(sql)

    def ensure_sync_state(self):
        """确保 sync_state 表存在。"""
        self.execute(SYNC_STATE_DDL)


# ---------------------------------------------------------------------------
# SQL 辅助
# ---------------------------------------------------------------------------


def sql_str(s) -> str:
    """转义为 SQL 字符串字面量;None → NULL。"""
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


def sql_int(v) -> str:
    """转义为 SQL 整数;None → NULL。"""
    if v is None:
        return "NULL"
    return str(int(v))


def build_upsert(table: str, conflict_cols: list[str],
                 fields: dict[str, str]) -> str:
    """构建 INSERT … ON CONFLICT DO UPDATE。
    只更新 fields 里出现的列,未列入的列在冲突时保持原值(安全 upsert)。
    """
    cols = list(fields.keys())
    col_list = ", ".join(cols)
    val_list = ", ".join(fields[c] for c in cols)
    set_list = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
    conflict = ", ".join(conflict_cols)
    return (
        f"INSERT INTO {table} ({col_list})\n"
        f"VALUES ({val_list})\n"
        f"ON CONFLICT ({conflict}) DO UPDATE SET\n"
        f"    {set_list};"
    )


# ---------------------------------------------------------------------------
# 解析 / 提取
# ---------------------------------------------------------------------------


def compute_hash(filepath: Path) -> str:
    """文件内容 sha256(幂等锚点)。"""
    return hashlib.sha256(filepath.read_bytes()).hexdigest()


def extract_section(body: str, title: str) -> str | None:
    """从 Markdown 正文提取 ## {title} 下的内容(到下一个 ## 或文末)。"""
    lines = body.split("\n")
    capturing = False
    result = []
    for line in lines:
        if re.match(r"^##\s+", line):
            if capturing:
                break
            if title in line:
                capturing = True
                continue
        elif capturing:
            result.append(line)
    text = "\n".join(result).strip()
    return text or None


def extract_chapter_sections(body: str) -> dict[str, str | None]:
    """从章节正文提取原文 / 今译 / 注释三个区段。"""
    sections: dict[str, list[str]] = {}
    cur = None
    for line in body.split("\n"):
        m = re.match(r"^##\s*(原文|今译|注释)\s*$", line.strip())
        if m:
            cur = m.group(1)
            sections[cur] = []
        elif cur is not None:
            sections[cur].append(line)

    def clean(lines: list[str]) -> str | None:
        t = "\n".join(lines).strip()
        return t or None

    return {
        "original_text": clean(sections.get("原文", [])),
        "translation": clean(sections.get("今译", [])),
        "annotation": clean(sections.get("注释", [])),
    }


def detect_type(filepath: Path) -> str | None:
    """根据文件路径判断内容类型(复用 TYPE_RULES 的 glob 模式)。"""
    rel = filepath.relative_to(CONTENT_ROOT).as_posix()
    for tkey, rule in TYPE_RULES.items():
        if fnmatch.fnmatch(rel, rule["glob"]):
            return tkey
    return None


# ---------------------------------------------------------------------------
# Slug 解析(预加载全表,避免逐条查询)
# ---------------------------------------------------------------------------


class SlugResolver:
    """预加载 eras / schools / persons / classics 的 slug→id 映射。"""

    def __init__(self, db: Db):
        self.eras = self._load(db, "eras")
        self.schools = self._load(db, "schools")
        self.persons = self._load(db, "persons")
        self.classics = self._load(db, "classics")
        self.domains = self._load(db, "domains", slug_col="code")

    @staticmethod
    def _load(db: Db, table: str, slug_col: str = "slug") -> dict[str, int]:
        rows = db.query(f"SELECT {slug_col}, id FROM {table};")
        return {r[0]: int(r[1]) for r in rows}

    def era(self, slug: str) -> int | None:
        return self.eras.get(slug)

    def school(self, slug: str) -> int | None:
        return self.schools.get(slug)

    def person(self, slug: str) -> int | None:
        return self.persons.get(slug)

    def classic(self, slug: str) -> int | None:
        return self.classics.get(slug)

    def domain(self, code: str) -> int | None:
        return self.domains.get(code)


# ---------------------------------------------------------------------------
# upsert SQL 构建(每种类型一个函数)
# ---------------------------------------------------------------------------


def build_person_sql(fm: dict, body: str, resolver: SlugResolver):
    """persons 表 upsert。返回 (sql, slug, error)。"""
    slug = fm["slug"]
    fields: dict[str, str] = {"slug": sql_str(slug)}

    if "name" in fm:
        fields["name"] = sql_str(fm["name"])
    if "name_en" in fm:
        fields["name_en"] = sql_str(fm.get("name_en"))
    if "courtesy_name" in fm:
        fields["courtesy_name"] = sql_str(fm.get("courtesy_name"))
    if "pseudonym" in fm:
        fields["pseudonym"] = sql_str(fm.get("pseudonym"))
    if "pinyin" in fm:
        fields["pinyin"] = sql_str(fm.get("pinyin"))
    if "birth_year" in fm:
        fields["birth_year"] = sql_int(fm.get("birth_year"))
    if "death_year" in fm:
        fields["death_year"] = sql_int(fm.get("death_year"))
    if fm.get("era_slug"):
        eid = resolver.era(fm["era_slug"])
        if eid is None:
            return None, slug, f"era_slug={fm['era_slug']!r} 在 DB 中不存在"
        fields["era_id"] = str(eid)
    if "summary" in fm:
        fields["summary"] = sql_str(fm.get("summary"))
    if "thought_position" in fm:
        fields["thought_position"] = sql_str(fm.get("thought_position"))
    # 派生:biography 从正文 ## 生平 提取
    bio = extract_section(body, "生平")
    if bio:
        fields["biography"] = sql_str(bio)
    # 状态
    if fm.get("retired"):
        fields["status"] = sql_str("RETIRED")
    elif "review_status" in fm:
        fields["status"] = sql_str(fm["review_status"])
    fields["updated_at"] = "NOW()"

    return build_upsert("persons", ["slug"], fields), slug, None


def build_concept_sql(fm: dict, resolver: SlugResolver):
    """concepts 表 upsert。返回 (sql, slug, error)。"""
    slug = fm["slug"]
    fields: dict[str, str] = {"slug": sql_str(slug)}

    if "name" in fm:
        fields["name"] = sql_str(fm["name"])
    if "name_en" in fm:
        fields["name_en"] = sql_str(fm.get("name_en"))
    if "pinyin" in fm:
        fields["pinyin"] = sql_str(fm.get("pinyin"))
    if fm.get("domain_code"):
        did = resolver.domain(fm["domain_code"])
        if did is None:
            return None, slug, f"domain_code={fm['domain_code']!r} 在 DB 中不存在"
        fields["domain_id"] = str(did)
    if "summary" in fm:
        fields["summary"] = sql_str(fm.get("summary"))
    # 状态
    if fm.get("retired"):
        fields["status"] = sql_str("RETIRED")
    elif "review_status" in fm:
        fields["status"] = sql_str(fm["review_status"])
    fields["updated_at"] = "NOW()"

    return build_upsert("concepts", ["slug"], fields), slug, None


def build_classic_sql(fm: dict, resolver: SlugResolver):
    """classics 表 upsert。返回 (sql, slug, error)。"""
    slug = fm["slug"]
    fields: dict[str, str] = {"slug": sql_str(slug)}

    if "title" in fm:
        fields["title"] = sql_str(fm["title"])
    if "title_en" in fm:
        fields["title_en"] = sql_str(fm.get("title_en"))
    if fm.get("author_slug"):
        aid = resolver.person(fm["author_slug"])
        if aid is None:
            return None, slug, f"author_slug={fm['author_slug']!r} 在 DB 中不存在"
        fields["author_id"] = str(aid)
    if fm.get("era_slug"):
        eid = resolver.era(fm["era_slug"])
        if eid is None:
            return None, slug, f"era_slug={fm['era_slug']!r} 在 DB 中不存在"
        fields["era_id"] = str(eid)
    if fm.get("school_slug"):
        sid = resolver.school(fm["school_slug"])
        if sid is None:
            return None, slug, f"school_slug={fm['school_slug']!r} 在 DB 中不存在"
        fields["school_id"] = str(sid)
    if "background" in fm:
        fields["background"] = sql_str(fm.get("background"))
    if "structure" in fm:
        fields["structure"] = sql_str(fm.get("structure"))
    if "core_thought" in fm:
        fields["core_thought"] = sql_str(fm.get("core_thought"))
    if "summary" in fm:
        fields["summary"] = sql_str(fm.get("summary"))
    if "compiled_year" in fm:
        fields["compiled_year"] = sql_int(fm.get("compiled_year"))
    if fm.get("domain"):
        d = fm["domain"]
        domains = ",".join(str(x) for x in d) if isinstance(d, list) else str(d)
        fields["domain"] = sql_str(domains)
    if fm.get("retired"):
        fields["status"] = sql_str("RETIRED")
    elif "review_status" in fm:
        fields["status"] = sql_str(fm["review_status"])
    fields["updated_at"] = "NOW()"

    return build_upsert("classics", ["slug"], fields), slug, None


def build_chapter_sql(fm: dict, body: str, resolver: SlugResolver):
    """classic_chapters 表 upsert。返回 (sql, slug, error)。"""
    classic_slug = fm["classic"]
    cid = resolver.classic(classic_slug)
    if cid is None:
        return None, classic_slug, f"classic={classic_slug!r} 在 DB 中不存在"

    ch_num = fm["chapter_number"]
    sections = extract_chapter_sections(body)

    fields: dict[str, str] = {
        "classic_id": str(cid),
        "chapter_number": str(ch_num),
    }
    if "chapter_title" in fm:
        fields["chapter_title"] = sql_str(fm.get("chapter_title"))
    # 原文必填,今译/注释可选
    fields["original_text"] = sql_str(sections["original_text"] or "")
    if sections["translation"]:
        fields["translation"] = sql_str(sections["translation"])
    if sections["annotation"]:
        fields["annotation"] = sql_str(sections["annotation"])
    fields["sort_order"] = str(ch_num)

    sql = build_upsert("classic_chapters", ["classic_id", "chapter_number"], fields)
    slug = f"{classic_slug}-{ch_num}"
    return sql, slug, None


def build_event_sql(fm: dict, body: str, resolver: SlugResolver):
    """events 表 upsert。返回 (sql, slug, error)。

    字段映射(与主仓库 events 表一致):
      slug / title / era_id(era_slug→era_id) / year(可为负) /
      summary / description(正文 ## 详述) / significance / status=PUBLISHED
    events 表零迁移,字段已完备(UNIQUE(slug))。
    """
    slug = fm["slug"]
    fields: dict[str, str] = {"slug": sql_str(slug)}

    if "title" in fm:
        fields["title"] = sql_str(fm["title"])
    if fm.get("era_slug"):
        eid = resolver.era(fm["era_slug"])
        if eid is None:
            return None, slug, f"era_slug={fm['era_slug']!r} 在 DB 中不存在"
        fields["era_id"] = str(eid)
    if "year" in fm:
        fields["year"] = sql_int(fm.get("year"))
    if "summary" in fm:
        fields["summary"] = sql_str(fm.get("summary"))
    # description 从正文 ## 详述 提取(可选)
    desc = extract_section(body, "详述")
    if desc:
        fields["description"] = sql_str(desc)
    if "significance" in fm:
        fields["significance"] = sql_str(fm.get("significance"))
    # events 默认 PUBLISHED(事实层已审,来自内容仓库即权威)
    fields["status"] = sql_str("PUBLISHED")
    fields["updated_at"] = "NOW()"

    return build_upsert("events", ["slug"], fields), slug, None


# ---------------------------------------------------------------------------
# 校验(增量:只校验当前文件)
# ---------------------------------------------------------------------------


def validate_single_file(fm: dict, body: str, rel: str, tkey: str,
                         authors: set[str]) -> list[str]:
    """对单个文件做增量校验,返回错误列表(空 = 通过)。

    复用 check.py 的 schema 校验 + 状态机 + AUTHORS 引用逻辑,
    但不跑全仓跨文件引用(FK 解析在 upsert 阶段自然验证)。
    """
    errors: list[str] = []

    # 1. schema 校验
    schema_file = SCHEMA_DIR / TYPE_RULES[tkey]["schema"]
    errors.extend(validate_schema(fm, schema_file))

    # 2. 状态机硬约束(README §3.2)
    status = fm.get("review_status")
    level = fm.get("credibility_level", "B")
    if level == "C" and status == "PUBLISHED":
        errors.append(f"{rel}: 状态机——credibility_level=C 不可 PUBLISHED")
    ai = fm.get("ai_used")
    contributors = fm.get("contributors") or []
    if ai and not contributors and status and status != "DRAFT":
        errors.append(f"{rel}: 状态机——ai_used 存在但无 contributors,不可离开 DRAFT")

    # 3. AUTHORS 引用完整性
    for field in ("contributors", "reviewers"):
        for item in fm.get(field) or []:
            aid = item.get("id") if isinstance(item, dict) else None
            if aid and aid not in authors:
                errors.append(f"{rel}: {field} 引用未注册的 AUTHORS ID: {aid!r}")

    # 4. 章节正文结构(仅 classic-chapter)
    if tkey == "classic-chapter":
        sections = extract_chapter_sections(body)
        if not sections["original_text"]:
            errors.append(f"{rel}: 章节缺少 [## 原文] 区段(必填)")

    return errors


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> int:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    verbose = "--verbose" in args
    psql_cmd = DEFAULT_PSQL_CMD
    for i, a in enumerate(args):
        if a == "--psql-cmd" and i + 1 < len(args):
            psql_cmd = args[i + 1]

    sys.stdout.reconfigure(encoding="utf-8")

    print(f"content/ 增量同步器 — root: {CONTENT_ROOT}")
    print(f"DB: {psql_cmd}")
    if dry_run:
        print("[DRY-RUN] 只读模式,不执行写操作")
    print()

    # --- 1. 收集所有文件 ---
    all_files: list[tuple[Path, str]] = []
    for tkey, rule in TYPE_RULES.items():
        if not (SCHEMA_DIR / rule["schema"]).exists():
            continue
        for f in sorted(CONTENT_ROOT.glob(rule["glob"])):
            all_files.append((f, tkey))
    print(f"扫描 content/ ... 发现 {len(all_files)} 个文件")

    # --- 2. 连 DB,读 sync_state ---
    db = Db(psql_cmd, verbose)
    try:
        if not dry_run:
            db.ensure_sync_state()
        sync_state: dict[str, str] = {}
        try:
            rows = db.query("SELECT path, content_hash FROM content_sync_state;")
            sync_state = {r[0]: r[1] for r in rows}
        except RuntimeError:
            if dry_run:
                print("  sync_state 表不存在,假设全部为新增")
            else:
                raise
        print(f"读取 sync_state ... 已记录 {len(sync_state)} 个文件")
    except RuntimeError as e:
        print(f"\nDB 连接失败: {e}")
        return 2

    # --- 3. 加载 slug 解析器 + AUTHORS ---
    resolver = SlugResolver(db)
    authors = extract_authors(_DummyReporter())
    print(f"slug 解析: eras={len(resolver.eras)}, schools={len(resolver.schools)}, "
          f"persons={len(resolver.persons)}, classics={len(resolver.classics)}")
    print()

    # --- 4. 逐文件处理:hash 对比 → 校验 → 构建 SQL ---
    batch: list[tuple[str, str, str, str, str]] = []  # (rel, hash, type, slug, sql)
    skipped = 0
    errors: list[str] = []

    print("处理变更:")
    for filepath, tkey in all_files:
        rel = filepath.relative_to(CONTENT_ROOT).as_posix()
        file_hash = compute_hash(filepath)

        # 幂等:hash 一致则跳过
        if rel in sync_state and sync_state[rel] == file_hash:
            skipped += 1
            if verbose:
                print(f"  = 跳过 {rel} (hash 一致)")
            continue

        # 解析 frontmatter
        try:
            fm, body = parse_frontmatter(filepath.read_text(encoding="utf-8"))
        except ValueError as e:
            errors.append(f"{rel}: frontmatter 解析失败 — {e}")
            print(f"  X {rel}: {e}")
            continue
        if fm is None:
            errors.append(f"{rel}: 缺少 frontmatter")
            print(f"  X {rel}: 缺少 frontmatter")
            continue

        # 增量校验
        file_errors = validate_single_file(fm, body, rel, tkey, authors)
        if file_errors:
            errors.extend(file_errors)
            for e in file_errors:
                print(f"  X {e}")
            continue

        # 构建 upsert SQL
        if tkey == "person":
            sql, slug, err = build_person_sql(fm, body, resolver)
        elif tkey == "concept":
            sql, slug, err = build_concept_sql(fm, resolver)
        elif tkey == "classic":
            sql, slug, err = build_classic_sql(fm, resolver)
        elif tkey == "classic-chapter":
            sql, slug, err = build_chapter_sql(fm, body, resolver)
        elif tkey == "event":
            sql, slug, err = build_event_sql(fm, body, resolver)
        else:
            print(f"  ~ {rel}: 类型 {tkey} 暂不支持同步,跳过")
            continue

        if err:
            errors.append(f"{rel}: {err}")
            print(f"  X {rel}: {err}")
            continue

        tag = "UPDATE" if rel in sync_state else "NEW"
        print(f"  + {rel} -> {tkey} (slug={slug}) [{tag}]")
        batch.append((rel, file_hash, tkey, slug, sql))

    # --- 5. 删除检测 ---
    current_paths = {
        fp.relative_to(CONTENT_ROOT).as_posix() for fp, _ in all_files
    }
    retired = [p for p in sync_state if p not in current_paths]
    if retired:
        print("\n删除检测:")
        for p in retired:
            print(f"  ! {p}: 文件已从 content/ 移除(将从 sync_state 清除,DB 实体保留)")

    # --- 6. 执行 ---
    if dry_run:
        print(f"\n===== DRY-RUN: 将处理 {len(batch)}, 跳过 {skipped}, "
              f"错误 {len(errors)}, 下架 {len(retired)} =====")
        print("(未执行任何写操作)")
    else:
        if batch:
            sql_parts = ["BEGIN;"]
            for rel, file_hash, tkey, slug, upsert_sql in batch:
                sql_parts.append(upsert_sql)
                # 更新 sync_state
                sql_parts.append(
                    "INSERT INTO content_sync_state "
                    "(path, content_hash, entity_type, slug, synced_at, status)\n"
                    f"VALUES ({sql_str(rel)}, {sql_str(file_hash)}, "
                    f"{sql_str(tkey)}, {sql_str(slug)}, NOW(), 'ok')\n"
                    "ON CONFLICT (path) DO UPDATE SET\n"
                    "    content_hash = EXCLUDED.content_hash,\n"
                    "    entity_type  = EXCLUDED.entity_type,\n"
                    "    slug         = EXCLUDED.slug,\n"
                    "    synced_at    = EXCLUDED.synced_at,\n"
                    "    status       = EXCLUDED.status,\n"
                    "    error        = NULL;"
                )
            sql_parts.append("COMMIT;")
            try:
                db.execute("\n".join(sql_parts))
            except RuntimeError as e:
                print(f"\n执行失败(事务已回滚): {e}")
                return 1

        # 删除检测:清理 sync_state 中已不存在的 path(DB 实体不动)
        if retired:
            del_parts = ["BEGIN;"]
            for p in retired:
                del_parts.append(
                    f"DELETE FROM content_sync_state WHERE path={sql_str(p)};"
                )
            del_parts.append("COMMIT;")
            db.execute("\n".join(del_parts))

        print(f"\n===== 同步完成: 处理 {len(batch)}, 跳过 {skipped}, "
              f"错误 {len(errors)}, 下架 {len(retired)} =====")

    # --- 7. 受影响 slug(供派生层重算) ---
    if batch:
        affected = ", ".join(s for _, _, _, s, _ in batch)
        print(f"受影响 slug(供派生层重算): {affected}")

    if errors:
        print(f"\n警告: {len(errors)} 个文件因校验错误被跳过,请修复后重新同步")
        return 1
    return 0


class _DummyReporter:
    """extract_authors 需要一个带 warn() 的对象,但不影响功能。"""

    def warn(self, msg: str):
        pass


if __name__ == "__main__":
    sys.exit(main())
