#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentUnify 机械比对器（比对 + 校验 + 机械下发，不做裁决）

定位（协作规则第六条）：
  - 脚本是「工具」，不是「大脑」
  - 比对（哈希）+ 校验（索引对齐）+ 机械下发（翻译覆盖），但不裁决
  - 冲突（内容不同/仅副本有）由 Owner 裁决，脚本只报告不自动覆盖
  - 增删改（归源/内容编辑）由 AI 按「协作规则」执行

真源：Obsidian（路径由 config.json 的 source_dir 指定，不写死在代码里）
副本：WorkBuddy ~/.workbuddy、Trae .trae-cn、ZCode ~/.zcode/workspace/default/inbox

两种现行下发形态（N:1 拼接已于 2026-09-13 废弃）：
  - 1:1（workbuddy/trae）  真源文件 -> 副本文件（改目录/改名），占位符翻译
  - inbox（zcode，2026-09-13 起）真源文件原样保留子目录拷入 inbox，ZCode 自己归位
    （README：~/.zcode/workspace/default/inbox/README.md，
      "原样丢进来、不用分类、不用改名、ZCode 整理归位"）

用法：
  python mirror.py compare        # 对比真源 vs 各工具副本，输出差异清单（默认）
  python mirror.py report         # 生成待裁决.md（仅当有冲突）
  python mirror.py check          # 校验索引对齐（AGENTS.md 懒加载总表 + 4-索引 双链地图）
  python mirror.py backup         # 全量备份真源内容到 _archive/备份-日期/
  （compare / check 为只读命令，不写盘、不触发备份）
  python mirror.py sync [tool]          # dry-run：报告三类差异（不改文件）
  python mirror.py sync --apply [tool]  # 只下发「仅真源有」（安全），内容不同/仅副本有停
  python mirror.py sync --apply --take-ob [tool]   # Owner 裁决「以真源为准」后，差异也覆盖副本

说明：
  - 工程分离（2026-09-14）：脚本 / 日志 / 备份都在工程侧，
    真源（Obsidian）只留内容 md，不放任何工程产物
  - MEMORY.md（记忆层）：WorkBuddy 侧 1:1 翻译下发；Trae 侧已删、不下发；ZCode 侧 inbox 直拷不翻译
  - 多工具映射：TOOLS 定义每个工具一张映射表，PATH_VARS 定义路径占位符翻译
  - 哈希前统一做两层归一化（行尾 CRLF -> LF、占位符 -> 工具实际路径），
    比的是「内容」而非「路径方言 / 行尾方言」
  - sync --apply 只下发「仅真源有」（真源新增、副本缺失），内容不同/仅副本有需 Owner 裁决
"""

import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta

__version__ = "0.3.0"   # 与 AgentUnify 项目版本同步（SemVer）
                        #   0.3.0 = 稳定性加固（命令白名单 / preflight / config 出声 / 写后复核）
                        #           + 行尾归一 + 4-索引双链守卫 + 独立 memindex.py

# 强制 stdout/stderr 用 UTF-8，避免 Windows cmd（GBK）双击运行时中文乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

# ============ 配置区 ============
# 脚本自定位（2026-09-14 工程分离）：脚本 / 日志 / 备份 / 配置都放在「脚本的上级目录」，
#   即工程侧目录（不进真源、不进版本库）。真源路径从该目录的 config.json 读。
_HOME       = os.path.expanduser("~")                      # #harden-portable：不写死用户名
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))   # 脚本目录
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)                  # 配置与产物的根目录（= 脚本的上级）
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")

def _load_config():
    """读 config.json（真源路径 / 技能目录等）。

    #harden-config 2026-09-14：原实现把「文件损坏」与「文件缺失」一并静默吞掉、
    返回 {} 后用兜底默认路径继续跑。config 是设计上唯一的环境适配点，
    它坏掉时反馈最差也最危险 —— 故损坏必须出声（缺失仍静默：那是合法首跑场景）。
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
# 默认值用占位符（而非任何真实路径）：config 缺失/未配时由 preflight() 指路退出，
# 既避免把机器路径写进代码，也让「私有版」与开源脱敏版共用同一份源码。
OB = os.path.normpath(os.path.expanduser(_CONFIG.get("source_dir", r"你的真源目录")))   # 支持 ~ 并规整分隔符

# source_dir 的占位符默认值：命中它说明 config.json 还没配好（缺文件或缺 source_dir）。
PLACEHOLDER_SOURCE_DIR = "你的真源目录"

def preflight():
    """启动前置校验：真源目录必须真实存在，否则给出清晰指引并退出。

    #harden-preflight 2026-09-14：原实现把「真源路径失效」拖到 backup() 里的
    os.listdir 才爆 FileNotFoundError —— 崩在 main() 第一步、无任何指引，所有命令全挂。
    config.json 是设计上唯一的环境适配点，它指错时反馈必须最清楚。
    """
    if not OB or OB == PLACEHOLDER_SOURCE_DIR or not os.path.isdir(OB):
        sys.stderr.write(
            "⛔ 真源目录不可用，已中止。\n"
            f"   当前 source_dir = {OB!r}\n"
            f"   配置文件       = {CONFIG_PATH}\n"
            "   请检查 config.json 的 source_dir 是否指向真实的真源文档目录。\n"
        )
        sys.exit(2)

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
            "3-记忆/MEMORY.md":   "MEMORY.md",   # 记忆层（2026-09-13 入实时比对）
            "ai_rules_collaboration.md": "user_rules/ai_rules_collaboration.md",
            "ai_rules_architecture.md":  "user_rules/ai_rules_architecture.md",
        },
        "rules_dir": "user_rules",   # 真源 2-规则/*.md -> <root>/<rules_dir>/*.md
        "exclude_rules": ["project_dir_rule.md"],  # 仅 Trae 用，WorkBuddy 本地副本已删
    },
    "trae": {
        "root": _CONFIG.get("trae_root", os.path.join(_HOME, ".trae-cn")),
        "files": {
            "AGENTS.md": "user_rules/AGENTS.md",
            "1-人设/USER.md": "memory/user_profile.md",   # 用户画像（Trae 下非常重要）
            # 2026-09-13 删除：3-记忆/MEMORY.md -> user_rules/MEMORY.md（Owner"全部删除悬挂"）
            "ai_rules_collaboration.md": "memory/ai_rules_collaboration.md",   # 体系宪法
            "ai_rules_architecture.md": "memory/ai_rules_architecture.md",     # 架构背景
            "2-规则/project_dir_rule.md": "user_rules/project_dir_rule.md",  # 例外：该规则在 Trae 是 user_rules\（自动加载）
            # 注：SOUL.md + IDENTITY.md -> user_rules/identity.md 是 N:1 合并，
            #     脚本不做机械比对，由 AI 下发 Trae 时手动合并（脚本只做 1:1）
        },
        "rules_dir": "memory",   # 真源 2-规则/*.md -> <root>/memory/*.md（触发加载）
        "exclude_rules": ["project_dir_rule.md"],  # 已在 files 显式映射到 user_rules，从 memory 遍历排除
    },
    "zcode": {
        "root": os.path.expanduser("~/.zcode"),
        # ZCode 接入 inbox 模式（2026-09-13 Owner 拍板）：
        # 真源所有要下发到 ZCode 的文件 → 原样保留文件名 + 保留子目录 → 拷入 inbox
        # ZCode 自己从 inbox 抓取、识别、按 README 三分流归位
        # （AGENTS.md / cli/memories/.../memory/ / Obsidian）。
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

# 当前参与比对的目标工具（接入顺序：WorkBuddy -> Trae -> ZCode；豆包无本地目录不参与）
# Trae 于 2026-09-13 真源中立化后归一化比对全 0，正式纳入自动监控（此前只手工核对）。
ACTIVE_TOOLS = ["workbuddy", "trae", "zcode"]

# ============ 路径占位符（真源中立化） ============
# 真源文件内容里用 {VAR} 表示「路径」，下发到各工具时按此表翻译成该工具的实际路径。
# 这样真源不写死 ~/.workbuddy，各工具副本各自翻译，compare 归一化后比的是「内容」而非「路径方言」。
PATH_VARS = {
    "{RULES_DIR}": {       # 主题规则目录（2-规则 大部分规则，Trae 下触发加载）
        "workbuddy": "~/.workbuddy/user_rules/",
        "trae": ".trae-cn/memory/",
        # zcode：inbox 模式不翻译（2026-09-13）
    },
    "{CORE_RULES_DIR}": {  # 核心规则目录（如 project_dir_rule，Trae 下自动加载）
        "workbuddy": "~/.workbuddy/user_rules/",
        "trae": ".trae-cn/user_rules/",
        # zcode：inbox 模式不翻译（2026-09-13）
    },
    "{MEMORY_FILE}": {     # 记忆库文件
        "workbuddy": "~/.workbuddy/MEMORY.md",
        "trae": ".trae-cn/user_rules/MEMORY.md",
        # zcode：inbox 模式不翻译（2026-09-13）
    },
    "{AGENTS_FILE}": {     # 最高统领文件
        "workbuddy": "~/.workbuddy/AGENTS.md",
        "trae": ".trae-cn/user_rules/AGENTS.md",
        # zcode：inbox 模式不翻译（2026-09-13）
    },
    "{SKILLS_DIR}": {      # 技能目录
        "workbuddy": "~/.workbuddy/skills/",
        "trae": ".trae-cn/skills/",
        # zcode：inbox 模式不翻译（2026-09-13）
    },
    "{BIN_DIR}": {         # 工具/脚本目录（命令执行用绝对路径）
        # #harden-portable：翻译结果与旧硬编码值逐字一致（~ 展开即 C:\Users\<用户>），
        # 换机器时不再需要改代码，只依赖家目录。
        "workbuddy": os.path.join(_HOME, ".workbuddy", "bin") + os.sep,
        "trae": os.path.join(_HOME, ".trae-cn", "scripts") + os.sep,
        # zcode：inbox 模式不翻译（2026-09-13）
    },
}

# 拼接文件时各段之间的分隔符（N:1 拼接用，字节级，保持 LF）
MERGE_SEP = b"\n\n---\n\n"

# 规则目录（真源侧）：2-规则/*.md 是所有工具共用的规则来源
RULES_OB = os.path.join(OB, "2-规则")
# 注：MEMORY.md 自 2026-09-13 起已纳入实时比对（见 TOOLS[*].files）；
#     「记忆定期提炼汇总」是内容治理策略（协作规则第八章），与镜像比对无关。

# 运行产物（日志/报告）与备份都落在工程侧，不再写进真源（2026-09-14 工程分离）
LOG_FILE = os.path.join(SCRIPT_DIR, "compare.log")     # 日志跟脚本同级

# 备份目录：真源内容文件备份到 _archive/备份-YYYY-MM-DD/
ARCHIVE_DIR = os.path.join(ROOT_DIR, "_archive")
# 真源根目录下的「非内容」目录：既不参与备份，也不参与索引对齐扫描
# （2026-09-14 工程分离后真源已不再含 _scripts/_archive，此处保留作防御性排除）
NON_CONTENT_DIRS = {"_scripts", "_archive", "_adapters"}

# 4-索引 双链地图（Obsidian [[双链]] 导航），由 check_links() 校验
INDEX_NAV = "4-索引/规则导航.md"
# 地图自身不参与「遗漏」统计（它是索引，不是被索引的对象）
NAV_SELF = {"规则导航"}

# ============ 工具函数 ============
def normalize_eol(data):
    """把 CRLF / 裸 CR 统一成 LF。

    2026-09-14 加固 #harden-eol：真源与副本可能因写盘方式不同带上行尾「方言」
    （真源被编辑器写成 CRLF、副本是 LF）。行尾不是 Markdown 的语义内容，
    却足以让原字节哈希报出 differ 假阳性 —— 故两侧哈希前统一归一化。
    """
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

def content_sha256(path, tool=None):
    """算文件「内容」哈希，哈希前做两层归一化，消除方言差异：

      1. 行尾归一化：CRLF / 裸 CR -> LF（所有工具通用）
      2. 路径归一化：真源里的 {VAR} 占位符 -> 该工具实际路径（仅指定 tool 时）

    这样比的是内容本身，而不是路径方言或行尾方言。
    """
    try:
        with open(path, "rb") as f:
            raw = normalize_eol(f.read())
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
    # newline="\n"：#harden-eol 2026-09-14 —— 本脚本就是做行尾归一化的工具，
    # 自己的日志更不该被 Windows 转成 CRLF。
    with open(LOG_FILE, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")

def bytes_sha256(data):
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()

def merged_bytes(sources, tool):
    """把多个真源文件按序机械拼成一个文件的字节内容（纯拼接，无内容取舍），并翻译占位符。

    用二进制读写 + 固定分隔符，保持 LF 不被 Windows 转成 CRLF。
    注：2026-09-13 起 zcode 改 inbox 模式，所有工具的 merge 字段均为 None，
       因此本函数的两个调用点（pair_ob_sha256 / sync）目前都不可达。
       保留供未来重新启用 N:1 拼接时使用；若确认永不启用，可连同
       MERGE_SEP 与各处 merge 分支一并删除。
    """
    parts = []
    for p in sources:
        with open(p, "rb") as f:
            parts.append(f.read().rstrip(b"\n"))
    return translate_content(MERGE_SEP.join(parts) + b"\n", tool)

def pair_ob_sha256(ob_path, tool, merges=None):
    """算「真源侧应有内容」归一化哈希：拼接型算拼接结果，1:1 型算单文件内容。

    2026-09-13 加固 #harden-bidir-scan：孤儿 pair（ob_path=None）直接返回 None，
    compare() 会把 None 哈希视为「真源没有」自动归入 only_wb 分支。
    """
    if ob_path is None:
        return None
    if merges:
        try:
            return bytes_sha256(normalize_eol(merged_bytes(merges, tool)))
        except OSError:
            return None
    return content_sha256(ob_path, tool)

def build_pairs(tools=None):
    """返回 [(真源路径, 副本路径, 工具名, 拼接源列表或None)]。

    1:1 型：真源路径 = 单个真源文件，拼接源 = None。
    拼接型（N:1）：真源路径 = None（无单一真源），拼接源 = 按序真源文件绝对路径列表。
    inbox 型（zcode）：真源多个文件 → inbox/<原路径>，拼接源 = None（直拷，不翻译）。

    2026-09-13 修复 #bug-rules_dir-condition：
      原条件 `and rd == "2-规则"` 误判，导致 rules_dir 不等于 "2-规则" 的工具
      （workbuddy/trae）的 2-规则/*.md 全部不进比对 → 静默漏报陈旧。
      桌面报告：AI-Rules-mirror.py-比对漏报BUG分析-2026-09-13.md
    2026-09-13 加固 #harden-bidir-scan：
      副本侧孤儿扫描 —— 真源已删、副本还有的文件自动归入「仅副本有」。
      inbox 模式跳过（inbox 由 ZCode 自己整理，"副本有但真源无" 可能是 ZCode 加工产物）。
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
        # 2026-09-13 修复 #bug-rules_dir-condition：去掉 `and rd == "2-规则"`
        # 真源侧规则目录永远是 RULES_OB；rd 只决定副本侧落点，与真源侧无关
        if rd and os.path.isdir(RULES_OB):
            for fn in sorted(os.listdir(RULES_OB)):
                if fn.endswith(".md") and fn not in excl:
                    pairs.append((os.path.join(RULES_OB, fn),
                                  os.path.join(base_dst, rd, fn), tool, None))
        # 2026-09-13 加固 #harden-bidir-scan：副本侧孤儿扫描
        # 副本 rules_dir 下有但真源任何位置都没有的文件 → 生成 (None, dst, tool, None) pair，
        # 由 compare() 自然归入「仅副本有」分支。
        # inbox 模式跳过（inbox 是 raw 拷贝，"副本有但真源无" 不等于孤儿）
        # 修复 v2：原写 `os.path.join(RULES_OB, fn)` 只查 2-规则/，会把根目录的
        # ai_rules_*.md 误判为孤儿。改为查全真源（所有子目录 + 根的 ai_rules_*.md）。
        # 修复 v3：files 字段里的改名映射（如 Trae USER.md → user_profile.md）也跳过，
        # 否则会把"副本用了别名"的合法情况误报为孤儿。
        if rd and inbox_rel is None:
            dst_rules_dir = os.path.join(root, rd)
            if os.path.isdir(dst_rules_dir):
                # 收集真源所有 .md 文件的 basename（一次性构建，复用于整个循环）
                ob_basenames = set()
                for top in os.listdir(OB):
                    if top.startswith('.') or top in NON_CONTENT_DIRS:
                        continue
                    full = os.path.join(OB, top)
                    if os.path.isdir(full):
                        for sub in os.listdir(full):
                            if sub.endswith(".md"):
                                ob_basenames.add(sub)
                    elif top.endswith(".md"):
                        ob_basenames.add(top)
                # 收集 files 字段里已映射到的目标 basename（改名映射，跳过扫描）
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
        if item in NON_CONTENT_DIRS:
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

def check_links():
    """校验 4-索引 双链地图 ↔ 真源实际 .md 文件 是否一一对应。

    2026-09-14 新增 #guard-index-nav：原 check_index() 只覆盖 AGENTS.md ↔ 2-规则/，
    4-索引/ 完全没有守卫 —— 文件名改了（如 obsidian_config.md -> 笔记MCP配置信息.md）
    地图里的 [[双链]] 就成了红链，且无人报错。本函数补上这段守卫。

    返回 (红链, 遗漏)：
      - 红链：地图里 [[链接]] 了、但真源没有该 .md（Obsidian 里显示为红色断链）
      - 遗漏：真源有该 .md、但地图没串上（导航失效，找不着）

    扫描范围：真源根目录 + 所有子目录的 .md，排除 NON_CONTENT_DIRS 与 NAV_SELF。
    """
    nav_path = os.path.join(OB, INDEX_NAV)
    if not os.path.isfile(nav_path):
        return [], []
    with open(nav_path, "r", encoding="utf-8") as f:
        nav = f.read()
    # 先剔掉围栏代码块与行内代码：那里出现的 [[xxx]] 多半是在「讲解双链语法」，
    # 不是真链接（如实测中 `[[双链]]` 被误判为红链）。剔完再扫，避免自我误报。
    nav_scan = re.sub(r"```.*?```", "", nav, flags=re.S)
    nav_scan = re.sub(r"`[^`]*`", "", nav_scan)
    # [[名字]] / [[名字|别名]] / [[名字#标题]] 统一取 [[ 与 ]|# 之间的名字
    linked = {m.strip() for m in re.findall(r"\[\[([^\]\|#]+)", nav_scan)}

    actual = set()
    for top in os.listdir(OB):
        if top.startswith(".") or top in NON_CONTENT_DIRS:
            continue
        full = os.path.join(OB, top)
        if os.path.isdir(full):
            actual.update(sub[:-3] for sub in os.listdir(full) if sub.endswith(".md"))
        elif top.endswith(".md"):
            actual.add(top[:-3])

    linked -= NAV_SELF
    actual -= NAV_SELF
    return sorted(linked - actual), sorted(actual - linked)

# ============ 核心对比 ============
def classify(pairs):
    """把配对逐一比较，归成三类差异。统一形状：每项 (真源路径, 副本路径, 工具, 拼接源|None)。

    #refactor-classify 2026-09-14：原 compare() 返回 2 元组、sync() 用 4 元组，
    同一套三分类逻辑逐字重复两遍 —— 改一处漏一处，两种元组形状还构成隐式契约。
    现只写一遍，调用方按需取字段。

    返回 (仅真源有, 仅副本有, 内容不同)。
    """
    only_ob, only_wb, differ = [], [], []
    for ob_path, wb_path, tool, merges in pairs:
        ob_h = pair_ob_sha256(ob_path, tool, merges)   # 真源侧：占位符→工具路径归一化
        wb_h = content_sha256(wb_path)                  # 副本侧：无占位符，只做行尾归一化
        if ob_h is None and wb_h is None:
            continue
        if ob_h is None:
            only_wb.append((ob_path, wb_path, tool, merges))   # 真源没有，副本有
        elif wb_h is None:
            only_ob.append((ob_path, wb_path, tool, merges))   # 真源有，副本没有
        elif ob_h != wb_h:
            differ.append((ob_path, wb_path, tool, merges))    # 两边都有但内容不同
    return only_ob, only_wb, differ

def compare():
    """对比真源 vs 副本，返回 (仅真源有, 仅副本有, 内容不同)，每项为 (真源路径, 副本路径)。"""
    only_ob, only_wb, differ = classify(build_pairs())
    return ([(ob, wb) for ob, wb, _t, _m in only_ob],
            [(ob, wb) for ob, wb, _t, _m in only_wb],
            [(ob, wb) for ob, wb, _t, _m in differ])

# ============ 机械下发（sync） ============
def translate_content(data, tool):
    """把字节内容里的占位符翻译成工具路径（二进制安全，保持换行符）。"""
    text = data.decode("utf-8")
    for var, mapping in PATH_VARS.items():
        text = text.replace(var, mapping.get(tool, var))
    return text.encode("utf-8")

def sync(tools, apply=False, take_ob=False):
    """sync 命令：dry-run 报告三类差异；apply 只下发「仅真源有」（翻译+二进制覆盖）。

    铁律：内容不同 / 仅副本有 一律不自动处理，交给 Owner 裁决。

    **例外 1 — inbox 模式（zcode）**：「内容不同」自动覆盖。inbox 是 raw 副本，
      「过期就该重写」是它的本质属性；「仅副本有」仍报裁决（可能是 ZCode 自己加工的产物）。

    **例外 2 — take_ob（2026-09-14 加入，须与 apply 同时显式给出）**：Owner 已裁决
      「以真源为准」后，把「内容不同」也按真源覆盖到非 inbox 副本。
      补的是体系原本缺失的一环 —— 没有它，真源改完的合法内容**永远推不到**
      WorkBuddy / Trae 副本（手动 cp 被明令禁止），形成死结。
      仍**不触碰**「仅副本有」。
    """
    only_ob, only_wb, differ = classify(build_pairs(tools))

    if not apply:
        print("# sync dry-run（只报告，不改文件）")
        print(f"- 仅真源有（将下发）：{len(only_ob)}")
        for ob, wb, tool, merges in only_ob:
            label = "（拼接）" if merges else ""
            print(f"  [{tool}] {os.path.basename(wb)}{label}")
        print(f"- 内容不同（需裁决{'；已指定 --take-ob，将按真源覆盖' if take_ob else ''}）：{len(differ)}")
        for ob, wb, tool, _m in differ:
            print(f"  [{tool}] {os.path.basename(wb)}")
        print(f"- 仅副本有（需裁决）：{len(only_wb)}")
        for ob, wb, tool, _m in only_wb:
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

    # 差异覆盖：inbox 自动（raw 副本过期即重写）；非 inbox 仅在 take_ob（Owner 裁决后）时执行
    overridden = 0
    for ob_path, wb_path, tool, _m in differ:
        is_inbox = bool(TOOLS[tool].get("inbox"))
        if not is_inbox and not take_ob:
            skipped_differ += 1
            continue
        with open(ob_path, "rb") as f:
            data = f.read()
        if not is_inbox:
            data = translate_content(data, tool)   # 非 inbox 需翻译占位符
        os.makedirs(os.path.dirname(wb_path), exist_ok=True)
        with open(wb_path, "wb") as f:
            f.write(data)
        applied += 1
        if is_inbox:
            print(f"  下发 [{tool}] {os.path.basename(wb_path)}（inbox 过期重写）")
        else:
            overridden += 1
            print(f"  下发 [{tool}] {os.path.basename(wb_path)}（--take-ob 以真源为准覆盖）")

    print(f"apply 完成：下发 {applied} 个")
    if overridden:
        print(f"↻ 其中 {overridden} 个是「内容不同」按真源覆盖（--take-ob，Owner 已裁决）")
    if skipped_differ:
        print(f"⏸ 跳过内容不同 {skipped_differ} 个（需 Owner 裁决；裁决为「以真源为准」后加 --take-ob 重跑）")
    if only_wb:
        print(f"⚠️ 待裁决：仅副本有 {len(only_wb)} 个，可能是 ZCode 自己加工的产物，请 Owner 确认")

    # #harden-verify 2026-09-14：写后复核 —— 重新分类一次，确认下发真的落到副本上了。
    # 原实现写完不做任何验证，"下发 N 个" 只是计数，落盘失败（权限 / 路径 / 编码）无从察觉。
    v_ob, v_wb, v_diff = classify(build_pairs(tools))
    print(f"🔍 复核：仅真源有 {len(v_ob)}／内容不同 {len(v_diff)}／仅副本有 {len(v_wb)}")
    if v_ob or v_diff:
        print("   ⚠️ 仍有未同步项 —— 下发可能未生效，请检查副本路径与写权限")

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
# 命令白名单：#harden-cli 2026-09-14 —— 原实现无白名单，未知命令静默落 else 分支
# 当 compare 跑：打错一个字（compaer）也会得到一份"正常"的报告、退出码 0，
# 在自动化 / 脚本调用里完全无法察觉。现在未知命令一律报错退出（exit 2）。
COMMANDS = ("compare", "report", "check", "backup", "sync")

# 只读命令：不写任何文件，故不需要写盘备份兜底。
# #harden-backup-scope 2026-09-14：原实现对 check 这种纯只读命令也做全量备份。
READONLY_COMMANDS = ("compare", "check")

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "compare"

    if mode not in COMMANDS:
        sys.stderr.write(
            f"⛔ 未知命令：{mode!r}\n"
            f"   可用命令：{' | '.join(COMMANDS)}\n"
        )
        sys.exit(2)

    # 真源可用性前置校验：路径失效时立刻指路退出，而不是留到 os.listdir 裸崩
    preflight()

    # 写操作前先备份（同一天只备份一次，安全回滚兜底）；只读命令跳过
    if mode not in READONLY_COMMANDS:
        backup()

    if mode == "backup":
        print(f"Backup done. See {ARCHIVE_DIR}")
        return

    if mode == "check":
        # 单独校验索引对齐（两段：AGENTS.md 懒加载总表 + 4-索引 双链地图）
        orphan, zombie = check_index()
        red, missing = check_links()
        print("# 索引对齐校验")
        print("## 1. AGENTS.md 懒加载总表 ↔ 真源规则文件")
        print(f"- 孤儿规则（有文件没引用）：{len(orphan)}")
        print(f"- 僵尸引用（有引用没文件）：{len(zombie)}")
        if orphan:
            print("\n⚠️ 孤儿规则（真源有、AGENTS.md 总表未引用）：")
            for fn in orphan:
                print(f"  - {fn}")
        if zombie:
            print("\n⚠️ 僵尸引用（AGENTS.md 引用了但真源没有）：")
            for fn in zombie:
                print(f"  - {fn}")
        if not orphan and not zombie:
            print("✅ 一一对应，无遗漏。")

        print(f"\n## 2. {INDEX_NAV} 双链地图 ↔ 真源 .md 文件")
        print(f"- 红链（有链接没文件）：{len(red)}")
        print(f"- 遗漏（有文件没链接）：{len(missing)}")
        if red:
            print("\n⚠️ 红链（Obsidian 里显示为断链、点不开）：")
            for n in red:
                print(f"  - [[{n}]]")
        if missing:
            print("\n⚠️ 遗漏（真源有但地图没串上）：")
            for n in missing:
                print(f"  - {n}.md")
        if not red and not missing:
            print("✅ 双链地图与真源文件一一对应。")

        log(f"Index check: orphan {len(orphan)}, zombie {len(zombie)}, red {len(red)}, missing {len(missing)}.")
        return

    if mode == "sync":
        args = sys.argv[2:]
        apply = "--apply" in args
        take_ob = "--take-ob" in args
        tools = [a for a in args if not a.startswith("--")]
        tools = tools if tools else ACTIVE_TOOLS
        bad = [t for t in tools if t not in TOOLS]
        if bad:
            print(f"未知工具: {bad}，可选 {list(TOOLS.keys())}")
            return
        if take_ob and not apply:
            print("⛔ --take-ob 必须与 --apply 同时显式给出")
            print("   它的语义是「Owner 已裁决：以真源为准覆盖副本」，不允许默认生效、不允许省略 --apply。")
            return
        if take_ob:
            print("⚠️ 已启用 --take-ob：『内容不同』也将按真源覆盖副本。")
            print("   仅在 Owner 裁决「以真源为准」之后使用；「仅副本有」不受影响、仍报裁决。\n")
        sync(tools, apply=apply, take_ob=take_ob)
        return

    only_ob, only_wb, differ = compare()
    report = render_report(only_ob, only_wb, differ)

    # compare/report 都附带索引校验结果（两段：总表对齐 + 双链地图）
    orphan, zombie = check_index()
    red, missing = check_links()
    if orphan or zombie or red or missing:
        report += "\n\n---\n\n# ⚠️ 索引对齐警告\n\n"
        if orphan:
            report += "## 孤儿规则（真源有、但 AGENTS.md 总表未引用）：\n\n"
            for fn in orphan:
                report += f"- {fn}\n"
            report += "\n"
        if zombie:
            report += "## 僵尸引用（AGENTS.md 引用了、但真源无此文件）：\n\n"
            for fn in zombie:
                report += f"- {fn}\n"
            report += "\n"
        if red:
            report += f"## 4-索引 红链（{INDEX_NAV} 链接了、但真源无此文件）：\n\n"
            for n in red:
                report += f"- [[{n}]]\n"
            report += "\n"
        if missing:
            report += f"## 4-索引 遗漏（真源有此 .md、但 {INDEX_NAV} 未串上）：\n\n"
            for n in missing:
                report += f"- {n}.md\n"
            report += "\n"

    if mode == "report":
        report_path = os.path.join(SCRIPT_DIR, "待裁决.md")
        with open(report_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(report)
        print(f"Report written to: {report_path}")
        log(f"Report generated: only_ob {len(only_ob)}, only_wb {len(only_wb)}, differ {len(differ)}.")
    else:  # compare
        print(report)
        log(f"Compare done: only_ob {len(only_ob)}, only_wb {len(only_wb)}, differ {len(differ)}.")

if __name__ == "__main__":
    main()
