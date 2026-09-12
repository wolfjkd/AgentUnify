#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentUnify 机械比对器（比对 + 校验 + 机械下发，不做裁决）

定位（协作规则第六条）：
  - 脚本是「工具」，不是「大脑」
  - 比对（哈希）+ 校验（索引对齐）+ 机械下发（翻译覆盖），但不裁决
  - 冲突（内容不同/仅副本有）由 Owner 裁决，脚本只报告不自动覆盖
  - 增删改（归源/内容编辑）由 AI 按「协作规则」执行

真源：Obsidian  D:\\你的用户名-OB\\你的用户名\\AI-Rules\\
副本：WorkBuddy ~/.workbuddy、Trae .trae-cn

用法：
  python mirror.py compare        # 对比真源 vs 各工具副本，输出差异清单（默认）
  python mirror.py report         # 生成待裁决.md（仅当有冲突）
  python mirror.py check          # 校验 AGENTS.md 索引 ↔ 规则文件是否一一对应
  python mirror.py backup         # 全量备份真源内容到 _archive/备份-日期/
  python mirror.py sync [tool]          # dry-run：报告三类差异（不改文件）
  python mirror.py sync --apply [tool]  # 只下发「仅真源有」（安全），内容不同/仅副本有停

说明：
  - MEMORY.md（记忆层）不参与实时比对，记忆走「定期提炼汇总」
  - 多工具映射：TOOLS 定义每个工具一张映射表，PATH_VARS 定义路径占位符翻译
  - sync --apply 只下发「仅真源有」（真源新增、副本缺失），内容不同/仅副本有需 Owner 裁决
"""

__version__ = "0.1.0"

import hashlib
import json
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
OB = r"你的真源目录"          # 真源（Obsidian），唯一真源

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
            "ai_rules_collaboration.md": "user_rules/ai_rules_collaboration.md",
            "ai_rules_architecture.md":  "user_rules/ai_rules_architecture.md",
        },
        "rules_dir": "user_rules",   # 真源 2-规则/*.md -> <root>/<rules_dir>/*.md
        "exclude_rules": [],  # 如需排除某规则（如仅某工具用），在此列出文件名
    },
    "trae": {
        "root": r"你的用户目录\.trae-cn",
        "files": {
            "AGENTS.md": "user_rules/AGENTS.md",
            "1-人设/USER.md": "memory/user_profile.md",   # 用户画像（Trae 下非常重要）
            "ai_rules_collaboration.md": "memory/ai_rules_collaboration.md",   # 体系宪法
            "ai_rules_architecture.md": "memory/ai_rules_architecture.md",     # 架构背景
            # 示例：如需「文件级例外」（某规则落不同目录），在此显式映射，如 "2-规则/某规则.md": "user_rules/某规则.md"
            # 注：SOUL.md + IDENTITY.md -> user_rules/identity.md 是 N:1 合并，
            #     脚本不做机械比对，由 AI 下发 Trae 时手动合并（脚本只做 1:1）
            # 注：3-记忆/MEMORY.md -> user_rules/MEMORY.md 是记忆映射，走「定期提炼汇总」不进实时比对
        },
        "rules_dir": "memory",   # 真源 2-规则/*.md -> <root>/memory/*.md（触发加载）
        "exclude_rules": [],  # 配合 files 显式映射，从 rules_dir 遍历排除
    },
    "zcode": {
        "root": os.path.expanduser("~/.zcode"),
        "files": {},   # TODO 单 AGENTS.md 合并模式（N:1），接入时定
        "rules_dir": None,
    },
    "doubao": {
        "root": None,
        "files": {},   # 无本地目录，手动（知识库上传 / 提示词指针）
        "rules_dir": None,
    },
}

# 当前参与比对的目标工具（骨架阶段只开 WorkBuddy，接入时逐个追加）
ACTIVE_TOOLS = ["workbuddy"]

# ============ 路径占位符（真源中立化） ============
# 真源文件内容里用 {VAR} 表示「路径」，下发到各工具时按此表翻译成该工具的实际路径。
# 这样真源不写死 ~/.workbuddy，各工具副本各自翻译，compare 归一化后比的是「内容」而非「路径方言」。
PATH_VARS = {
    "{RULES_DIR}": {       # 主题规则目录（2-规则 大部分规则，Trae 下触发加载）
        "workbuddy": "~/.workbuddy/user_rules/",
        "trae": ".trae-cn/memory/",
    },
    "{CORE_RULES_DIR}": {  # 核心规则目录（文件级例外时，Trae 下自动加载）
        "workbuddy": "~/.workbuddy/user_rules/",
        "trae": ".trae-cn/user_rules/",
    },
    "{MEMORY_FILE}": {     # 记忆库文件
        "workbuddy": "~/.workbuddy/MEMORY.md",
        "trae": ".trae-cn/user_rules/MEMORY.md",
    },
    "{AGENTS_FILE}": {     # 最高统领文件
        "workbuddy": "~/.workbuddy/AGENTS.md",
        "trae": ".trae-cn/user_rules/AGENTS.md",
    },
    "{SKILLS_DIR}": {      # 技能目录
        "workbuddy": "~/.workbuddy/skills/",
        "trae": ".trae-cn/skills/",
    },
    "{BIN_DIR}": {         # 工具/脚本目录（命令执行用绝对路径）
        "workbuddy": "C:\\Users\\你的用户名\\.workbuddy\\bin\\",
        "trae": "C:\\Users\\你的用户名\\.trae-cn\\scripts\\",
    },
}

# 规则目录（真源侧）：2-规则/*.md 是所有工具共用的规则来源
RULES_OB = os.path.join(OB, "2-规则")
# 注意：MEMORY.md 不参与实时比对（记忆走「定期提炼汇总」，见协作规则第八章）

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

def build_pairs(tools=None):
    """返回 [(真源路径, 副本路径, 工具名)] 列表。tools=None 时用 ACTIVE_TOOLS。"""
    tools = tools or ACTIVE_TOOLS
    pairs = []
    for tool in tools:
        cfg = TOOLS[tool]
        root = cfg.get("root")
        if not root:
            continue   # 无本地目录的工具（如豆包）跳过
        for ob_rel, dst_rel in cfg["files"].items():
            pairs.append((os.path.join(OB, ob_rel), os.path.join(root, dst_rel), tool))
        rd = cfg.get("rules_dir")
        excl = set(cfg.get("exclude_rules", []))
        if rd and os.path.isdir(RULES_OB):
            for fn in sorted(os.listdir(RULES_OB)):
                if fn.endswith(".md") and fn not in excl:
                    pairs.append((os.path.join(RULES_OB, fn), os.path.join(root, rd, fn), tool))
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

    for ob_path, wb_path, tool in pairs:
        ob_h = content_sha256(ob_path, tool)   # 真源侧：占位符→工具路径归一化
        wb_h = sha256(wb_path)                  # 副本侧：已是工具路径，直接哈希

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
    """
    pairs = build_pairs(tools)
    only_ob, only_wb, differ = [], [], []
    for ob_path, wb_path, tool in pairs:
        ob_h = content_sha256(ob_path, tool)
        wb_h = sha256(wb_path)
        if ob_h is None and wb_h is None:
            continue
        if ob_h is None:
            only_wb.append((ob_path, wb_path, tool))
        elif wb_h is None:
            only_ob.append((ob_path, wb_path, tool))
        elif ob_h != wb_h:
            differ.append((ob_path, wb_path, tool))

    if not apply:
        print("# sync dry-run（只报告，不改文件）")
        print(f"- 仅真源有（将下发）：{len(only_ob)}")
        for ob, wb, tool in only_ob:
            print(f"  [{tool}] {os.path.basename(ob)}")
        print(f"- 内容不同（需裁决）：{len(differ)}")
        for ob, wb, tool in differ:
            print(f"  [{tool}] {os.path.basename(ob)}")
        print(f"- 仅副本有（需裁决）：{len(only_wb)}")
        for ob, wb, tool in only_wb:
            print(f"  [{tool}] {os.path.basename(wb)}")
        return

    applied = 0
    for ob_path, wb_path, tool in only_ob:
        with open(ob_path, "rb") as f:
            data = translate_content(f.read(), tool)
        os.makedirs(os.path.dirname(wb_path), exist_ok=True)
        with open(wb_path, "wb") as f:
            f.write(data)
        applied += 1
        print(f"  下发 [{tool}] {os.path.basename(ob_path)}")
    print(f"apply 完成：下发 {applied} 个")
    if differ or only_wb:
        print(f"⚠️ 待裁决：内容不同 {len(differ)}、仅副本有 {len(only_wb)}，请 Owner 裁决后手动处理")

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
            lines.append(f"### {os.path.basename(ob_path)}")
            lines.append(f"- 真源：`{ob_path}`")
            lines.append(f"- 副本：`{wb_path}`")
            lines.append(f"- 状态：两边内容不同，需 Owner 确认以哪边为准。")
            lines.append("")

    if only_ob:
        lines.append("## 仅真源有（副本缺失，AI 按协作规则决定是否下发）")
        lines.append("")
        for ob_path, wb_path in only_ob:
            lines.append(f"- `{os.path.basename(ob_path)}`")
        lines.append("")

    if only_wb:
        lines.append("## 仅副本有（真源缺失，AI 按协作规则决定是否上报真源）")
        lines.append("")
        for ob_path, wb_path in only_wb:
            lines.append(f"- `{os.path.basename(wb_path)}`")
        lines.append("")

    if not (differ or only_ob or only_wb):
        lines.append("✅ 真源与副本完全一致，无需处理。")
        lines.append("")

    return "\n".join(lines)

# ============ 入口 ============
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "compare"

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
