# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/) 规范。

## [0.3.1] - 2026-09-14

### Added
- **真源口径分层（按文件夹切分）**：真源根级的 3 篇方法论（`ai_rules_architecture.md` / `ai_rules_collaboration.md` / `AI-Rules镜像同步规范.md`）为**框架层**，可脱敏开源；`1-人设/` `2-规则/` `3-记忆/` `4-索引/` 四个目录内的**一切**文档为**私人实例**，禁止开源。判据机械可判、零裁量
- **发布器覆盖方法论 md**：`publish.py` 从「只同步 2 个脚本」扩为多文件流水线（脚本 + 方法论 md 走同一条单向发布），新增**路径翻译**（真源机器路径 → 占位符、私有运行布局 → 本仓等价布局）与**两级守卫**（硬拦真实账号 / 机器路径 → 拒绝写入；软替换人名 / 项目名）
- **`2-规则/README.md`** 空槽位说明：与本仓 `1-人设` / `3-记忆` / `4-索引` 三个空槽位对齐
- **`ai_rules_architecture.md` 演进 8 / 演进 9**：回填「ZCode inbox 直拷取代 N:1 拼接」与「副本侧双向遍历加固」两段决策史

### Changed
- **`AI-Rules镜像同步规范.md` 从 `2-规则/` 移至仓根**（与另两篇方法论同级）；`mirror.py` 三工具 `TOOLS` 补显式映射，保证副本落点不变、镜像不误报
- **`check_index()` 校验范围**：由「`2-规则/*.md` + 根级 `ai_rules_*.md`」扩为「`2-规则/*.md` + 根级全部 `.md`（AGENTS.md 除外）」，避免规范移出后被误报为「僵尸引用」
- **`开源边界契约.md` 判据升级**：由「脱敏后能不能进」改为**「文件夹即口径」**；方法论 md 明确为**发布产物**，因此不对其做漂移比对
- **`README.md` / `AGENTS.md`** 按新口径重写：目录树、文档索引、开源边界
- 两脚本 `__version__` 同步至 `0.3.1`

### Removed
- **N:1 拼接死代码彻底清除**（0.3.0 仅在 docstring 里标注「可删」而保留）：`MERGE_SEP` 常量、`merged_bytes()`、`bytes_sha256()`（随之失去唯一调用点）、`TOOLS[*].merge` 死配置、`build_pairs()` 的拼接分支，以及全链路 `merges` 字段 —— 配对元组由 4 元统一为 3 元。自 2026-09-13 ZCode 改 inbox 模式后该路径已不可达，留着只会误导后续维护
- 本仓 `2-规则/AI-Rules镜像同步规范.md`（内容移至仓根，目录改为空槽位）

### Fixed
- `report` 命令的 docstring 与实现不符：原写「生成 `待裁决.md`（仅当有冲突）」，实际实现是**无条件写盘**（无论有无差异都留痕）

## [0.3.0] - 2026-09-14

### Added
- **`memindex.py` 索引层工具**：从技能目录机械扫描生成 `4-索引/技能清单.md`（`check` / `diff` / `gen`），把「手工维护必然漂移」的清单变成可完全再生的产物
- **`check` 扩展为两段校验**：① AGENTS.md 懒加载总表 ↔ 真源规则文件；② `4-索引/规则导航.md` 双链地图 ↔ 真源 `.md`（红链 / 遗漏）
- **`config.json` 配置机制**：真源路径、技能目录从代码里抽出来，换机器只改这一个文件（附 `config.example.json`）；支持 `~` 展开
- **命令白名单**：未知命令报错退出（exit 2），不再静默降级为 `compare`
- **前置校验 `preflight()`**：真源路径失效时给出清晰指路并退出，不再抛裸 `FileNotFoundError`
- **`sync --apply --take-ob`**：Owner 裁决「以真源为准」后，把「内容不同」也安全覆盖到副本的唯一合规通道（必须与 `--apply` 同时显式给出，无默认值）
- **写后复核**：`sync --apply` 结束后自动重跑分类并打印复核结果
- **`开源边界契约.md`**：把「机制进仓 / 实例不进仓」写成一条可执行的边界 —— 脚本两份、单向发布、发布前守卫扫描
- `.gitignore` 忽略 `config.json` 与运行时产物

### Changed
- **行尾统一 LF**：脚本自身与生成物一律 LF，消除体系内的行尾方言
- **`classify()` 抽取**：`compare()` 与 `sync()` 中重复的三分类逻辑合并为一处，返回统一形状
- **`OB` 默认值改为占位符**：不再把机器绝对路径写进源码，缺失时由 `preflight()` 指路
- **只读命令跳过备份**：`compare` / `check` 不再触发全量备份写盘
- **根目录变量改名** `LOCAL_DIR` → `ROOT_DIR`：语义为「配置与运行产物的根目录」

### Removed
- 死配置 `project_dir`（定义后从未被读取）
- 死字段 `name`（解析后即丢弃）
- N:1 拼接残留代码路径

### Fixed
- 未知命令静默降级、config 损坏静默吞错、真源路径失效裸崩 —— 三处「错了也不出声」的行为

## [0.2.0] - 2026-09-13

### Added
- **三种下发形态**：1:1 翻译下发（WorkBuddy / Trae）+ inbox 直拷（ZCode，v0.2.0 起新机制）
- **`sync` 命令补齐**：dry-run 报告三类差异；`--apply` 下发「仅真源有」
- **双向遍历加固**：副本侧孤儿扫描（真源已删、副本还有 → 自动归入「仅副本有」）
- **MEMORY.md 入实时比对**：v0.2.0 起 MEMORY.md 纳入 `TOOLS["workbuddy"]/["trae"]` files 字典；ZCode inbox 模式直拷
- **inbox 模式特例**：sync apply 对 inbox 工具的「内容不同」自动覆盖（raw 副本过期就该重写）
- **ZCode 边界铁律**：`~/.zcode/` 下所有文件是 ZCode 自己家务，本体系永不触碰
- **`pair_ob_sha256` None 防御**：兼容加固生成的孤儿 pair（ob_path=None）

### Changed
- **`build_pairs` 重构**：去掉硬编码 `rd == "2-规则"` 错误条件；真源侧规则目录恒为 `RULES_OB`，副本侧落点由 `rules_dir` 决定
- **`build_pairs` 加固段**：副本侧扫描改为查全真源（OB 根 + 所有子目录的 .md），并跳过 `files` 字段里已改名映射的目标，避免误报
- **`AGENTS.md` §1.1**：增加 ZCode 工具（inbox 模式描述）
- **`2-规则/AI-Rules镜像同步规范.md`**：5 命令表格更新；新增「inbox 直拷」+「ZCode 边界铁律」+「双向遍历」段落；描述 v0.2.0 sync 行为
- **README.md**：增加 ZCode + inbox 机制说明；目录结构图标注各工具对应路径

### Deprecated
- **N:1 拼接型（ZCode）**：v0.2.0 起 inbox 取代；旧 ZCode AGENTS.md 单文件拼接方案不再推荐

### Removed
- 无（仅弃用 N:1，机制仍保留在代码里供未来可能重新启用）

## [0.1.0] - 2026-09-13

### Added
- 首次提交：多智能体统一规则体系框架
- `mirror.py` 机械比对器（compare / check / backup / sync 四命令）
- 真源中立化机制（路径占位符 `PATH_VARS` + 归一化比对）
- 多工具映射（TOOLS 映射表，支持 workbuddy / trae / zcode / doubao）
- 三条铁律 + 三类文件治理（人设规则 / 记忆 / 索引）
- 协作规则（`ai_rules_collaboration.md`）与架构文档（`ai_rules_architecture.md`）
