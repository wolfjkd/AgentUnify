#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memindex.py - AI-Rules 索引层工具（4-索引/ 里「可自动生成」的那部分）

分工（与 mirror.py 划清边界）：
  - mirror.py   ：镜像比对 + AGENTS.md 懒加载总表对齐 + 4-索引/规则导航.md 双链守卫
  - memindex.py ：4-索引/技能清单.md 的**生成**与**校验**

为什么技能清单必须机器生成：
  「技能清单」是从 skills 目录机械扫出来的产物，手工维护必然漂移 ——
  实际情况正是如此：清单停留在 2026-09-12，且解析出的后缀有脏值
  （`— {}`、空值、`name:` 前缀噪音）。可自动生成的东西就不该手写。

真源：Obsidian（路径由 config.json 的 source_dir 指定，不写死在代码里）
技能来源：~/.workbuddy/skills/（skill 可执行体所在处，可由 --skills-dir 覆盖）

用法：
  python memindex.py check              # 只读校验：技能清单 vs skills 目录实际（默认）
  python memindex.py diff               # 打印将要写入的内容（dry-run，不落盘）
  python memindex.py gen                # 扫描 skills 目录，重建 4-索引/技能清单.md
  python memindex.py --skills-dir <路径> <命令>   # 覆盖技能来源目录

铁律（沿用体系宪法）：
  - 只写 4-索引/技能清单.md 这一个文件，绝不碰任何其它真源文件
  - check / diff 只读；gen 必须显式调用才落盘
  - 生成物行尾统一 LF（与镜像体系一致，避免 compare 的行尾方言）
  - 技能清单是**可完全再生**的产物，故 gen 前不做备份（备份意义不大，重跑即可）
"""

import json
import os
import re
import sys
from datetime import datetime

__version__ = "0.3.0"   # 与 AgentUnify 项目版本同步（SemVer）

# 强制 stdout/stderr 用 UTF-8，避免 Windows cmd（GBK）双击运行时中文乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

# ============ 配置区 ============
# 脚本自定位（2026-09-14 工程分离）：config.json / 运行产物都放在「脚本的上级目录」，
#   即工程侧目录（不进真源、不进版本库）。
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))   # 脚本目录
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)                  # 配置与产物的根目录（= 脚本的上级）
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")

def _load_config():
    """读 config.json（真源路径 / 技能目录等）。

    #harden-config 2026-09-14：与 mirror.py 同一约定 —— 缺失静默（合法首跑），
    损坏必须出声。config 是唯一的环境适配点，坏掉时反馈最差也最危险。
    """
    if not os.path.isfile(CONFIG_PATH):
        return {}          # 首次运行、尚未建 config：静默走内置默认值
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except ValueError as e:
        sys.stderr.write(
            f"⚠️ config.json 解析失败（{e}），已回退内置默认路径。\n"
            f"   文件：{CONFIG_PATH}\n"
        )
        return {}
    except OSError as e:
        sys.stderr.write(
            f"⚠️ config.json 读取失败（{e}），已回退内置默认路径。\n"
            f"   文件：{CONFIG_PATH}\n"
        )
        return {}

_CONFIG = _load_config()

# 真源（Obsidian），唯一真源 —— 路径不写死在代码里，改 config.json 即可
OB = os.path.normpath(os.path.expanduser(_CONFIG.get("source_dir", r"你的真源目录")))   # 支持 ~ 并规整分隔符
PLACEHOLDER_SOURCE_DIR = "你的真源目录"

def preflight():
    """启动前置校验：真源目录必须真实存在，否则指路退出。

    #harden-preflight 2026-09-14：与 mirror.py 同一约定。原实现会在 read_text() /
    open(TARGET) 处爆 FileNotFoundError，无任何指引。
    """
    if not OB or OB == PLACEHOLDER_SOURCE_DIR or not os.path.isdir(OB):
        sys.stderr.write(
            "⛔ 真源目录不可用，已中止。\n"
            f"   当前 source_dir = {OB!r}\n"
            f"   配置文件       = {CONFIG_PATH}\n"
            "   请检查 config.json 的 source_dir 是否指向真实的真源文档目录。\n"
        )
        sys.exit(2)

TARGET_REL = os.path.join("4-索引", "技能清单.md")                # 本脚本唯一写入的真源文件
TARGET = os.path.join(OB, TARGET_REL)
DEFAULT_SKILLS_DIR = os.path.normpath(os.path.expanduser(_CONFIG.get("skills_dir", "~/.workbuddy/skills")))

DESC_MAX = 60            # 索引里 description 的截断长度（字符）
TIMESTAMP_MARK = "> 自动生成："   # 时间戳行前缀：校验时忽略该行（重生成必然变）

# ============ 工具函数 ============
def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

def write_text_lf(path, text):
    """按 LF 行尾写文件（不给 Windows 转 CRLF 的机会）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

def parse_frontmatter(text):
    """解析 SKILL.md 顶部的 YAML frontmatter，返回 {key: value}（只取顶层标量）。

    支持 `key: value`、`key: "value"`，以及折叠块 `key: >` / `key: |` 后跟缩进行。
    目的是拿到 name / description，不追求完整 YAML 兼容。
    """
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, flags=re.S)
    if not m:
        return {}
    lines = m.group(1).splitlines()
    fm = {}
    i = 0
    while i < len(lines):
        mm = re.match(r"^([A-Za-z_][\w\-]*)[ \t]*:[ \t]*(.*)$", lines[i])
        if not mm:
            i += 1
            continue
        key = mm.group(1).lower()
        val = mm.group(2).strip()
        if val in (">", "|", ">-", "|-", ">+", "|+"):
            # 折叠 / 字面块：收拢后续缩进行为一行
            block = []
            i += 1
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
                block.append(lines[i].strip())
                i += 1
            val = " ".join(x for x in block if x)
        else:
            i += 1
        fm.setdefault(key, val.strip().strip("\"'").strip())
    return fm

def scan_skills(skills_dir):
    """扫描 skills 目录，返回按目录名排序的 [(目录名, description, 状态)]。

    - 跳过非目录条目（如 _bm_skillid_migration.json）与下划线/点开头的目录
    - 状态取值："" 正常 / "缺 SKILL.md" / "无 frontmatter" / "无 description"
    """
    if not os.path.isdir(skills_dir):
        return None
    items = []
    for entry in sorted(os.listdir(skills_dir)):
        full = os.path.join(skills_dir, entry)
        if not os.path.isdir(full) or entry.startswith(("_", ".")):
            continue
        skill_md = os.path.join(full, "SKILL.md")
        if not os.path.isfile(skill_md):
            items.append((entry, "", "缺 SKILL.md"))
            continue
        fm = parse_frontmatter(read_text(skill_md))
        # #refactor-deadfield 2026-09-14：原实现解析了 frontmatter 的 name 却从未渲染
        # （render 里收到 _name 直接丢弃）—— 死数据会漂移，删掉。
        desc = fm.get("description", "")
        if not fm:
            state = "无 frontmatter"
        elif not desc:
            state = "无 description"
        else:
            state = ""
        items.append((entry, desc, state))
    return items

def one_line(text, limit=DESC_MAX):
    """压成单行并截断，用于索引展示。"""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"

def index_line(dirname, desc, state):
    """渲染单个 skill 的索引行。缺失信息如实标注，不编造也不留空。"""
    d = one_line(desc)
    if d:
        return f"- **{dirname}** — {d}"
    if state:
        return f"- **{dirname}** — （{state}）"
    return f"- **{dirname}** — （无 description）"

# ============ 生成 ============
def render_skills_index(items, stamp=None):
    """渲染 4-索引/技能清单.md 的完整内容（LF）。"""
    stamp = stamp or datetime.now().strftime("%Y-%m-%d %H:%M")
    bad = [x for x in items if x[2]]
    L = []
    L.append("# 技能清单索引")
    L.append("")
    L.append(f"{TIMESTAMP_MARK}{stamp}")
    L.append("> 说明：由 AgentUnify 项目 `memindex.py gen` 机械扫描生成，**请勿手改**（改了下一次 gen 会冲掉）。")
    L.append("> skill 可执行体保留在 `{SKILLS_DIR}`，此处仅列索引。")
    L.append("")
    tail = f"，其中 {len(bad)} 个信息不完整（见下）" if bad else ""
    L.append(f"共 {len(items)} 个 skill{tail}。")
    L.append("")
    for dirname, desc, state in items:
        L.append(index_line(dirname, desc, state))
    L.append("")
    return "\n".join(L)

def strip_timestamp(text):
    """抹掉时间戳行与尾随空行，供校验时做「内容等价」比较。"""
    body = [ln for ln in text.splitlines() if not ln.startswith(TIMESTAMP_MARK)]
    return "\n".join(body).strip()

# ============ 校验 ============
def check(skills_dir):
    """只读校验：技能清单 vs skills 目录实际。返回 (是否一致, 明细列表)。"""
    items = scan_skills(skills_dir)
    if items is None:
        return False, [f"技能来源目录不存在：{skills_dir}"]
    if not os.path.isfile(TARGET):
        return False, [f"技能清单不存在：{TARGET_REL}（跑 `memindex.py gen` 生成）"]

    expected = strip_timestamp(render_skills_index(items, stamp=""))
    on_disk = strip_timestamp(read_text(TARGET))
    if expected == on_disk:
        return True, [f"技能清单与 skills 目录一致（{len(items)} 个）"]

    # 不一致：列出差异明细，便于判断是「新增 / 消失 / 描述变了」
    def bullets(text):
        out = {}
        for line in text.splitlines():
            m = re.match(r"^- \*\*(.+?)\*\*(?: — (.*))?$", line)
            if m:
                out[m.group(1)] = (m.group(2) or "").strip()
        return out

    old, new = bullets(on_disk), bullets(expected)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(new) & set(old) if new[k] != old[k])

    detail = []
    if added:
        detail.append(f"新增未入清单（{len(added)}）：" + "、".join(added))
    if removed:
        detail.append(f"清单有但目录已无（{len(removed)}）：" + "、".join(removed))
    if changed:
        detail.append(f"内容已变（{len(changed)}）：" + "、".join(changed))
    if not (added or removed or changed):
        detail.append("条目一致但渲染格式不同 → 旧版生成器产物，重新 gen 即可归位")
    bad = [x for x in items if x[2]]
    if bad:
        detail.append(f"信息不完整 {len(bad)} 个：" + "、".join(f"{x[0]}（{x[2]}）" for x in bad))
    return False, detail

# ============ 入口 ============
def main():
    argv = sys.argv[1:]
    preflight()
    skills_dir = DEFAULT_SKILLS_DIR
    if "--skills-dir" in argv:
        i = argv.index("--skills-dir")
        if i + 1 < len(argv):
            skills_dir = argv[i + 1]
            del argv[i:i + 2]
        else:
            print("--skills-dir 需要跟一个路径")
            return
    mode = argv[0] if argv else "check"

    if mode == "check":
        print("# 技能清单校验")
        print(f"- 真源文件：{TARGET_REL}")
        print(f"- 技能来源：{skills_dir}")
        ok, detail = check(skills_dir)
        if ok:
            print(f"✅ {detail[0]}")
        else:
            print("⚠️ 技能清单与技能来源不一致：")
            for d in detail:
                print(f"  - {d}")
            print("\n→ 跑 `python memindex.py gen` 重新生成")
        log(f"Skill index check: {'consistent' if ok else 'drifted'}.")
        return

    if mode in ("diff", "gen"):
        items = scan_skills(skills_dir)
        if items is None:
            print(f"技能来源目录不存在：{skills_dir}")
            return
        new = render_skills_index(items)
        if mode == "diff":
            old = read_text(TARGET) if os.path.isfile(TARGET) else ""
            print(f"# 技能清单 dry-run（不落盘）— 将写入 {TARGET_REL}\n")
            print(new)
            print("--- 变更摘要 ---")
            print(f"当前清单 {len(old.encode('utf-8'))} 字节 → 将写入 {len(new.encode('utf-8'))} 字节")
            print(f"扫描到 skill {len(items)} 个")
            return
        write_text_lf(TARGET, new)
        print(f"已生成：{TARGET_REL}（{len(items)} 个 skill，LF 行尾）")
        log(f"Skill index generated: {len(items)} items.")
        return

    sys.stderr.write(
        f"⛔ 未知命令：{mode!r}\n"
        "   用法：python memindex.py [gen|check|diff] [--skills-dir <路径>]\n"
    )
    sys.exit(2)

if __name__ == "__main__":
    main()
