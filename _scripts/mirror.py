#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentUnify 机械比对器（比对 + 校验 + 机械下发，不做裁决）

⚠️ 本文件是 **AgentUnify 的脱敏参考骨架**，不是本机运行版。
   本机实际运行的是私有版 `<项目>/_local/_scripts/mirror.py`（_local/ 已 gitignore，不进版本库）。
   两者**同名不同物**：骨架供对外发布，能力可能落后私有版（行尾归一化 / 4-索引双链守卫 /
   `--take-ob` 等均为私有版后续新增）。误跑本文件不会破坏数据（OB 是占位符，会自检退出），
   但它也不是你的运行版 —— 别用它。

定位（协作规则第六条）：
  - 脚本是「工具」，不是「大脑」
  - 比对（哈希）+ 校验（索引对齐）+ 机械下发（翻译覆盖），但不裁决
  - 冲突（内容不同/仅副本有）由 Owner 裁决，脚本只报告不自动覆盖
  - 增删改（归源/内容编辑）由 AI 按「协作规则」执行

真源：Obsidian <你的真源目录>（本文件为脱敏骨架，非本机运行版）
副本：WorkBuddy ~/.workbuddy、Trae .trae-cn、ZCode ~/.zcode/workspace/default/inbox

三种下发形态（v0.2.0）：
  - 1:1   真源文件 -> 副本文件（改目录/改名），WorkBuddy、Trae 走这条
  - inbox 真源文件原样保留子目录拷入 inbox，由 ZCode 自己识别归位
  - （旧 N:1 拼接型已弃用，inbox 取代）

用法：
  python mirror.py compare        # 对比真源 vs 各工具副本，输出差异清单（默认）
  python mirror.py report         # 生成待裁决.md（仅当有冲突）
  python mirror.py check          # 校验 AGENTS.md 索引 ↔ 规则文件是否一一对应
  python mirror.py backup         # 全量备份真源内容到 _archive/备份-日期/
  python mirror.py sync [tool]          # dry-run：报告三类差异（不改文件）
  python mirror.py sync --apply [tool]  # 只下发「仅真源有」（安全），内容不同/仅副本有停

说明：
  - MEMORY.md（记忆层）走 inbox 模式直拷（v0.2.0 起），不参与占位符翻译
  - 多工具映射：TOOLS 定义每个工具一张映射表，PATH_VARS 定义路径占位符翻译
  - sync --apply 只下发「仅真源有」（真源新增、副本缺失），内容不同/仅副本有需 Owner 裁决
  - **inbox 模式特例**：「内容不同」自动覆盖 —— inbox 是 raw 副本，过期就该重写是其本质；
    「仅副本有」仍报裁决（可能是 ZCode 加工产物）
  - v0.2.0 加固：副本侧孤儿扫描（真源已删、副本还有 → 自动归入「仅副本有」）
"""

__version__ = "0.2.0"

import hashlib
import os
import shutil
import sys
from datetime import datetime, timedelta

# 强制 stdout/stderr 用 UTF-8，避免 Windows cmd（GBK）双击运行时中文乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

# ============ 配置区 ============
OB = r"你的真源目录"          # ⚠️ 占位符：脱敏骨架使用前须改成你自己的真源目录

# ============ 多工具映射（骨架） ============
# 真源唯一：Obsidian；每个工具一张映射表，把中立内容「翻译」到该工具的形态。
# 本脚本只做「1:1 改名/换目录」的机械比对；合并(N:1)/内容改写由 AI 接入时完成。
TOOLS = {
    "workbuddy": {
        "root": os.path.expanduser("~/.workbuddy"),
        "files": {
            "AGENTS.md":           "AGENTS.md",
            "1-人设/SOUL.md":     "SOUL.md",
            "1-人设/IDENTITY.md": "IDENTITY.md",
            "1-人设/USER.md":     "USER.md",
            "3-记忆/MEMORY.md":   "MEMORY.md",   # v0.2.0 起入实时比对
            "ai_rules_collaboration.md": "user_rules/ai_rules_collaboration.md",
            "ai_rules_architecture.md":  "user_rules/ai_rules_architecture.md",
        },
        "rules_dir": "user_rules",   # 真源 2-规则/*.md -> <root>/<rules_dir>/*.md
        "exclude_rules": [],  # 如需排除某规则，在此列出文件名
    },
    "trae": {
        "root": r"你的用户目录\.trae-cn",
        "files": {
            "AGENTS.md": "user_rules/AGENTS.md",
            "1-人设/USER.md": "memory/user_profile.md",   # 用户画像（Trae 下非常重要）
            "ai_rules_collaboration.md": "memory/ai_rules_collaboration.md",   # 体系宪法
            "ai_rules_architecture.md": "memory/ai_rules_architecture.md",     # 架构背景
            # 注：SOUL.md + IDENTITY.md -> user_rules/identity.md 是 N:1 合并，
            #     脚本不做机械比对，由 AI 下发 Trae 时手动合并（脚本只做 1:1）
        },
        "rules_dir": "memory",   # 真源 2-规则/*.md -> <root>/memory/*.md（触发加载）
        "exclude_rules": [],
    },
    "zcode": {
        "root": os.path.expanduser("~/.zcode"),
        # ZCode 接入 inbox 模式（v0.2.0 起）：
        # 真源所有要下发到 ZCode 的文件 → 原样保留文件名 + 保留子目录 → 拷入 inbox
        # ZCode 自己从 inbox 抓取、识别、按 README 三分流归位
        # （行为规则 / 事实记忆 / 长篇参考）。
        # 我们只做机械直拷：不做 N:1 拼接、不做路径翻译、不做分类、不做改名。
        "inbox": "workspace/default/inbox",   # 相对 root 的 inbox 目录
        "files": {
            # 真源相对路径 -> inbox 内相对路径（保留真源子目录）
            "AGENTS.md":                    "AGENTS.md",
            "ai_rules_architecture.md":     "ai_rules_architecture.md",
            "ai_rules_collaboration.md":    "ai_rules_collaboration.md",
            "1-人设/SOUL.md":              "1-人设/SOUL.md",
            "1-人设/IDENTITY.md":          "1-人设/IDENTITY.md",
            "1-人设/USER.md":              "1-人设/USER.md",
            "3-记忆/MEMORY.md":            "3-记忆/MEMORY.md",
        },
        "rules_dir": "2-规则",   # 真源 2-规则/*.md → inbox/2-规则/*.md（整目录保留）
        "exclude_rules": [],
        "merge": None,   # 不再做 N:1 拼接
    },
    "doubao": {
        "root": None,
        "files": {},   # 无本地目录，手动（知识库上传 / 提示词指针）
        "rules_dir": None,
    },
}

# 当前参与比对的目标工具
# 接入顺序：WorkBuddy -> Trae -> ZCode；豆包无本地目录不参与
ACTIVE_TOOLS = ["workbuddy", "trae", "zcode"]

# ============ 路径占位符（真源中立化） ============
# 真源文件内容里用 {VAR} 表示「路径」，下发到各工具时按此表翻译成该工具的实际路径。
# 这样真源不写死 ~/.workbuddy，各工具副本各自翻译，compare 归一化后比的是「内容」而非「路径方言」。
#
# v0.2.0 变更：zcode 改 inbox 模式后，PATH_VARS 不再为 zcode 翻译占位符
# （inbox 是 raw 副本，ZCode 归位时自己决定路径；content_sha256 在 zcode 分支
# 会 fallback 到原占位符，即「不替换」，与 inbox 直拷语义一致）。
PATH_VARS = {
    "{RULES_DIR}": {       # 主题规则目录（2-规则 大部分规则，Trae 下触发加载）
        "workbuddy": "~/.workbuddy/user_rules/",
        "trae": ".trae-cn/memory/",
        # zcode：inbox 模式不翻译，保持原占位符
    },
    "{CORE_RULES_DIR}": {  # 核心规则目录（如 project_dir_rule，Trae 下自动加载）
        "workbuddy": "~/.workbuddy/user_rules/",
        "trae": ".trae-cn/user_rules/",
        # zcode：同上不翻译
    },
    "{MEMORY_FILE}": {     # 记忆库文件
        "workbuddy": "~/.workbuddy/MEMORY.md",
        "trae": ".trae-cn/user_rules/MEMORY.md",
        # zcode：同上不翻译
    },
    "{AGENTS_FILE}": {     # 最高统领文件
        "workbuddy": "~/.workbuddy/AGENTS.md",
        "trae": ".trae-cn/user_rules/AGENTS.md",
        # zcode：同上不翻译
    },
    "{SKILLS_DIR}": {      # 技能目录
        "workbuddy": "~/.workbuddy/skills/",
        "trae": ".trae-cn/skills/",
        # zcode：同上不翻译
    },
    "{BIN_DIR}": {         # 工具/脚本目录（命令执行用绝对路径）
        "workbuddy": "C:\\Users\\你的用户名\\.workbuddy\\bin\\",
        "trae": "C:\\Users\\你的用户名\\.trae-cn\\scripts\\",
        # zcode：同上不翻译
    },
}

# 拼接文件时各段之间的分隔符（保留供未来可能启用 N:1 拼接时使用）
MERGE_SEP = b"\n\n---\n\n"

# 规则目录（真源侧）：2-规则/*.md 是所有工具共用的规则来源
RULES_OB = os.path.join(OB, "2-规则")

LOG_FILE = os.path.join(OB, "_scripts", "compare.log")

# 备份目录：真源内容文件备份到 _archive/备份-YYYY-MM-DD/
ARCHIVE_DIR = os.path.join(OB, "_archive")
# 备份时排除的条目（真源根目录下的「非内容」目录，不参与备份）
BACKUP_EXCLUDE = {"_scripts", "_archive"}

# ============ 工具函数 ============
def sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None

def content_sha256(path, tool=None):
    """算文件内容哈希；若指定 tool，先把内容里的占位符翻译成该工具路径再哈希（路径归一化）。"""
    try:
        with open(path, "rb") as f:
            raw = f.read()
        if tool:
            text = raw.decode("utf-8")
            for var, mapping in PATH_VARS.items():
                text = text.replace(var, mapping.get(tool, var))
            raw = text.encode("utf-8")
        h = hashlib.sha256()
        h.update(raw)
        return h.hexdigest()
    except OSError:
        return None

def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def bytes_sha256(data):
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()

def merged_bytes(sources, tool):
    """把多个真源文件按序机械拼成一个文件的字节内容（纯拼接，无内容取舍），并翻译占位符。

    用二进制读写 + 固定分隔符，保持 LF 不被 Windows 转成 CRLF。
    注：v0.2.0 起 inbox 模式取代 N:1 拼接，本函数目前已无调用方（merge 字段为 None），
       保留供未来可能重新启用 N:1 拼接时使用。
    """
    parts = []
    for p in sources:
        with open(p, "rb") as f:
            parts.append(f.read().rstrip(b"\n"))
    return translate_content(MERGE_SEP.join(parts) + b"\n", tool)

def pair_ob_sha256(ob_path, tool, merges=None):
    """算「真源侧应有内容」归一化哈希：拼接型算拼接结果，1:1 型算单文件内容。

    v0.2.0 加固：孤儿 pair（ob_path=None）直接返回 None，
    compare() 会把 None 哈希视为「真源没有」自动归入 only_wb 分支。
    """
    if ob_path is None:
        return None
    if merges:
        try:
            return bytes_sha256(merged_bytes(merges, tool))
        except OSError:
            return None
    return content_sha256(ob_path, tool)

def build_pairs(tools=None):
    """返回 [(真源路径, 副本路径, 工具名, 拼接源列表或None)]。

    1:1 型：真源路径 = 单个真源文件，拼接源 = None。
    inbox 型：真源多个文件 → inbox/<原路径>，拼接源 = None（直拷，不翻译）。

    v0.2.0 双向遍历：副本侧孤儿扫描 —— 真源已删、副本还有的文件自动归入「仅副本有」。
    inbox 模式跳过双向遍历（inbox 由 ZCode 自己整理，"副本有但真源无" 不等于孤儿）。
    """
    tools = tools or ACTIVE_TOOLS
    pairs = []
    for tool in tools:
        cfg = TOOLS[tool]
        root = cfg.get("root")
        if not root:
            continue   # 无本地目录的工具（如豆包）跳过
        # inbox 模式：所有目标都在 inbox 下（zcode 专属）
        inbox_rel = cfg.get("inbox")
        base_dst = os.path.join(root, inbox_rel) if inbox_rel else root

        for ob_rel, dst_rel in cfg["files"].items():
            pairs.append((os.path.join(OB, ob_rel), os.path.join(base_dst, dst_rel), tool, None))
        rd = cfg.get("rules_dir")
        excl = set(cfg.get("exclude_rules", []))
        # 真源侧规则目录遍历：RULES_OB 是真源唯一规则目录，rd 只决定副本侧落点
        if rd and os.path.isdir(RULES_OB):
            for fn in sorted(os.listdir(RULES_OB)):
                if fn.endswith(".md") and fn not in excl:
                    pairs.append((os.path.join(RULES_OB, fn),
                                  os.path.join(base_dst, rd, fn), tool, None))
        # 双向遍历（v0.2.0 加固）：副本侧孤儿扫描
        # 副本 rules_dir 下有但真源任何位置都没有的文件 → 生成 (None, dst, tool, None) pair，
        # 由 compare() 自然归入「仅副本有」分支。
        # inbox 模式跳过（inbox 是 raw 拷贝，"副本有但真源无" 不等于孤儿）
        if rd and inbox_rel is None:
            dst_rules_dir = os.path.join(root, rd)
            if os.path.isdir(dst_rules_dir):
                # 收集真源所有 .md 文件的 basename（一次性构建）
                ob_basenames = set()
                for top in os.listdir(OB):
                    if top.startswith('.') or top in {"_archive", "_scripts", "_adapters"}:
                        continue
                    full = os.path.join(OB, top)
                    if os.path.isdir(full):
                        for sub in os.listdir(full):
                            if sub.endswith(".md"):
                                ob_basenames.add(sub)
                    elif top.endswith(".md"):
                        ob_basenames.add(top)
                # files 字段里已改名映射的，跳过扫描（如 trae USER.md → user_profile.md）
                mapped_basenames = {os.path.basename(dst) for dst in cfg["files"].values()}
                for fn in sorted(os.listdir(dst_rules_dir)):
                    if not fn.endswith(".md") or fn in excl:
                        continue
                    if fn in ob_basenames or fn in mapped_basenames:
                        continue   # 真源有，或 files 字段已改名映射，不算孤儿
                    # 真源任何位置都没有且 files 里没改名 → 副本孤儿
                    pairs.append((None, os.path.join(dst_rules_dir, fn), tool, None))
        mg = cfg.get("merge")
        if mg:   # N:1 拼接型：多真源 -> 单副本文件
            srcs = [os.path.join(OB, s) for s in mg["sources"]]
            pairs.append((None, os.path.join(root, mg["target"]), tool, srcs))
    return pairs

# ============ 备份（回滚机制） ============
def backup():
    """把真源内容全量备份到 _archive/备份-YYYY-MM-DD/。

    规则：同一天只备份一次（用「昨天日期」命名，代表「今天操作前的原始状态」）。
    范围：真源根目录下除 _scripts、_archive 外的所有条目（文件 + 目录全量），
         新增文件自动纳入，无需维护清单。
    """
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    backup_dir = os.path.join(ARCHIVE_DIR, f"备份-{yesterday}")

    if os.path.isdir(backup_dir):
        log(f"Backup skipped: {backup_dir} already exists.")
        return False

    os.makedirs(backup_dir, exist_ok=True)
    count = 0
    for item in os.listdir(OB):
        if item in BACKUP_EXCLUDE:
            continue
        src = os.path.join(OB, item)
        dst = os.path.join(backup_dir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
            count += 1
        elif os.path.isfile(src):
            shutil.copy2(src, dst)
            count += 1
    log(f"Backup done: {count} item(s) -> {backup_dir}")
    return True

# ============ 索引对齐校验 ============
def check_index():
    """校验 AGENTS.md 懒加载总表引用的规则 ↔ 真源实际规则文件 是否一一对应。

    返回 (孤儿规则, 僵尸引用)：
      - 孤儿规则：真源有、但 AGENTS.md 总表没引用（AI 不会主动读，最危险）
      - 僵尸引用：AGENTS.md 总表引用了、但真源没有该文件

    实际规则文件范围：2-规则/ 下的所有 .md + 根目录的 ai_rules_*.md
    """
    import re
    # 1. 实际规则文件：2-规则/ 下的 .md + 根目录 ai_rules_*.md
    actual = set()
    rules_dir = os.path.join(OB, "2-规则")
    if os.path.isdir(rules_dir):
        actual.update(fn for fn in os.listdir(rules_dir) if fn.endswith(".md"))
    for fn in os.listdir(OB):
        if fn.startswith("ai_rules_") and fn.endswith(".md"):
            actual.add(fn)

    # 2. AGENTS.md 总表里引用的规则文件（匹配 {RULES_DIR}xxx.md 等占位符形式，含中文文件名）
    agents_path = os.path.join(OB, "AGENTS.md")
    referenced = set()
    if os.path.isfile(agents_path):
        with open(agents_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 匹配 {RULES_DIR}xxx.md / {CORE_RULES_DIR}xxx.md（\w 含中文，支持中文文件名）
        for m in re.findall(r"\{[A-Z_]+DIR\}([\w\-]+\.md)", content):
            referenced.add(m)

    # 3. 双向对比
    orphan = sorted(actual - referenced)      # 有文件没引用
    zombie = sorted(referenced - actual)      # 有引用没文件

    return orphan, zombie

# ============ 核心对比 ============
def compare():
    """对比真源 vs 副本，返回 (仅真源有, 仅副本有, 两边不同) 三类清单。"""
    pairs = build_pairs()
    only_ob, only_wb, differ = [], [], []

    for ob_path, wb_path, tool, merges in pairs:
        ob_h = pair_ob_sha256(ob_path, tool, merges)   # 真源侧：占位符→工具路径归一化
        wb_h = sha256(wb_path)                          # 副本侧：已是工具路径，直接哈希

        if ob_h is None and wb_h is None:
            continue
        if ob_h is None:
            only_wb.append((ob_path, wb_path))   # 真源没有，副本有
            continue
        if wb_h is None:
            only_ob.append((ob_path, wb_path))   # 真源有，副本没有
            continue
        if ob_h != wb_h:
            differ.append((ob_path, wb_path))    # 两边都有但内容不同

    return only_ob, only_wb, differ

# ============ 机械下发（sync） ============
def translate_content(data, tool):
    """把字节内容里的占位符翻译成工具路径（二进制安全，保持换行符）。"""
    text = data.decode("utf-8")
    for var, mapping in PATH_VARS.items():
        text = text.replace(var, mapping.get(tool, var))
    return text.encode("utf-8")

def sync(tools, apply=False):
    """sync 命令：dry-run 报告三类差异；apply 只下发「仅真源有」（翻译+二进制覆盖）。

    铁律：内容不同 / 仅副本有 一律不自动处理，交给 Owner 裁决。
    **例外**：inbox 模式（zcode）的「内容不同」自动覆盖 —— inbox 是 raw 副本，
    「过期就该重写」是它的本质属性；「仅副本有」仍报裁决（可能是 ZCode 自己加工的产物）。
    """
    pairs = build_pairs(tools)
    only_ob, only_wb, differ = [], [], []
    for ob_path, wb_path, tool, merges in pairs:
        ob_h = pair_ob_sha256(ob_path, tool, merges)
        wb_h = sha256(wb_path)
        if ob_h is None and wb_h is None:
            continue
        if ob_h is None:
            only_wb.append((ob_path, wb_path, tool))
        elif wb_h is None:
            only_ob.append((ob_path, wb_path, tool, merges))
        elif ob_h != wb_h:
            differ.append((ob_path, wb_path, tool))

    if not apply:
        print("# sync dry-run（只报告，不改文件）")
        print(f"- 仅真源有（将下发）：{len(only_ob)}")
        for ob, wb, tool, merges in only_ob:
            label = "（拼接）" if merges else ""
            print(f"  [{tool}] {os.path.basename(wb)}{label}")
        print(f"- 内容不同（需裁决）：{len(differ)}")
        for ob, wb, tool in differ:
            print(f"  [{tool}] {os.path.basename(wb)}")
        print(f"- 仅副本有（需裁决）：{len(only_wb)}")
        for ob, wb, tool in only_wb:
            print(f"  [{tool}] {os.path.basename(wb)}")
        return

    applied = 0
    skipped_differ = 0
    for ob_path, wb_path, tool, merges in only_ob:
        if merges:
            data = merged_bytes(merges, tool)
        elif TOOLS[tool].get("inbox"):
            # inbox 模式（zcode）：原样直拷，不翻译占位符（ZCode 归位时自己处理）
            with open(ob_path, "rb") as f:
                data = f.read()
        else:
            with open(ob_path, "rb") as f:
                data = translate_content(f.read(), tool)
        os.makedirs(os.path.dirname(wb_path), exist_ok=True)
        with open(wb_path, "wb") as f:
            f.write(data)
        applied += 1
        label = "（拼接）" if merges else ("（inbox 直拷）" if TOOLS[tool].get("inbox") else "")
        print(f"  下发 [{tool}] {os.path.basename(wb_path)}{label}")

    # inbox 模式特例：内容不同也自动覆盖（inbox 是 raw 副本，过期就该重写）
    if apply:
        for ob_path, wb_path, tool in differ:
            if not TOOLS[tool].get("inbox"):
                skipped_differ += 1
                continue
            with open(ob_path, "rb") as f:
                data = f.read()   # inbox 模式不翻译
            with open(wb_path, "wb") as f:
                f.write(data)
            applied += 1
            print(f"  下发 [{tool}] {os.path.basename(wb_path)}（inbox 过期重写）")

    print(f"apply 完成：下发 {applied} 个")
    if skipped_differ:
        print(f"⏸ 跳过内容不同 {skipped_differ} 个（非 inbox 模式，需 Owner 裁决）")
    if only_wb:
        print(f"⚠️ 待裁决：仅副本有 {len(only_wb)} 个，可能是 ZCode 自己加工的产物，请 Owner 确认")

# ============ 输出报告 ============
def render_report(only_ob, only_wb, differ):
    lines = []
    lines.append("# AI-Rules 对比报告")
    lines.append("")
    lines.append(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append(f"- 仅真源有（副本缺失）：{len(only_ob)}")
    lines.append(f"- 仅副本有（真源缺失）：{len(only_wb)}")
    lines.append(f"- 两边都有但内容不同（需裁决）：{len(differ)}")
    lines.append("")

    if differ:
        lines.append("## ⚠️ 内容不一致（请 Owner 裁决，本脚本不改任何文件）")
        lines.append("")
        for ob_path, wb_path in differ:
            name = os.path.basename(ob_path or wb_path)
            tag = "（拼接型）" if ob_path is None else ""
            lines.append(f"### {name}{tag}")
            lines.append(f"- 真源：`{ob_path if ob_path else '（多个真源文件拼接，见 TOOLS 配置）'}`")
            lines.append(f"- 副本：`{wb_path}`")
            lines.append(f"- 状态：两边内容不同，需 Owner 确认以哪边为准。")
            lines.append("")

    if only_ob:
        lines.append("## 仅真源有（副本缺失，AI 按协作规则决定是否下发）")
        lines.append("")
        for ob_path, wb_path in only_ob:
            tag = "（拼接型）" if ob_path is None else ""
            lines.append(f"- `{os.path.basename(ob_path or wb_path)}`{tag}")
        lines.append("")

    if only_wb:
        lines.append("## 仅副本有（真源缺失，AI 按协作规则决定是否上报真源）")
        lines.append("")
        for ob_path, wb_path in only_wb:
            tag = "（拼接型）" if ob_path is None else ""
            lines.append(f"- `{os.path.basename(ob_path or wb_path)}`{tag}")
        lines.append("")

    if not (differ or only_ob or only_wb):
        lines.append("✅ 真源与副本完全一致，无需处理。")
        lines.append("")

    return "\n".join(lines)

# ============ 入口 ============
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "compare"

    # #harden-guard 2026-09-14：本文件是脱敏骨架，OB 默认值是占位符，
    # 照跑会崩在 backup() 的 os.listdir(OB)，且崩法像普通配置问题、难以判断。
    # 启动即自检并指路，避免把"拿错脚本"误诊为"配置写错"。
    if not os.path.isdir(OB):
        sys.stderr.write(
            "⛔ 真源目录未配置（脱敏骨架的默认值是占位符 「你的真源目录」）。\n"
            "   · 若你在 AgentUnify 本机运行 → 请改用 _local/_scripts/mirror.py（私有运行版）。\n"
            "   · 若你是外部使用者        → 请把源码顶部的 OB 改成你自己的真源目录。\n"
        )
        sys.exit(2)

    # 每次操作前先尝试备份（同一天只备份一次，安全回滚兜底）
    backup()

    if mode == "backup":
        print("Backup done. See _archive/")
        return

    if mode == "check":
        # 单独校验索引对齐
        orphan, zombie = check_index()
        print("# 索引对齐校验")
        print(f"- 孤儿规则（有文件没引用）：{len(orphan)}")
        print(f"- 僵尸引用（有引用没文件）：{len(zombie)}")
        if orphan:
            print("\n## ⚠️ 孤儿规则（AGENTS.md 总表未引用）：")
            for fn in orphan:
                print(f"  - {fn}")
        if zombie:
            print("\n## ⚠️ 僵尸引用（AGENTS.md 引用了但文件不存在）：")
            for fn in zombie:
                print(f"  - {fn}")
        if not orphan and not zombie:
            print("\n✅ 索引与规则文件一一对应，无遗漏。")
        log(f"Index check: orphan {len(orphan)}, zombie {len(zombie)}.")
        return

    if mode == "sync":
        args = sys.argv[2:]
        apply = "--apply" in args
        tools = [a for a in args if a != "--apply"]
        tools = tools if tools else ACTIVE_TOOLS
        bad = [t for t in tools if t not in TOOLS]
        if bad:
            print(f"未知工具: {bad}，可选 {list(TOOLS.keys())}")
            return
        sync(tools, apply=apply)
        return

    only_ob, only_wb, differ = compare()
    report = render_report(only_ob, only_wb, differ)

    # compare/report 都附带索引校验结果
    orphan, zombie = check_index()
    if orphan or zombie:
        report += "\n\n---\n\n# ⚠️ 索引对齐警告\n\n"
        if orphan:
            report += "## 孤儿规则（2-规则/ 有、但 AGENTS.md 总表未引用）：\n\n"
            for fn in orphan:
                report += f"- {fn}\n"
            report += "\n"
        if zombie:
            report += "## 僵尸引用（AGENTS.md 引用了、但 2-规则/ 无此文件）：\n\n"
            for fn in zombie:
                report += f"- {fn}\n"
            report += "\n"

    if mode == "report":
        report_path = os.path.join(OB, "_scripts", "待裁决.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report written to: {report_path}")
        log(f"Report generated: only_ob {len(only_ob)}, only_wb {len(only_wb)}, differ {len(differ)}.")
    else:  # compare
        print(report)
        log(f"Compare done: only_ob {len(only_ob)}, only_wb {len(only_wb)}, differ {len(differ)}.")

if __name__ == "__main__":
    main()