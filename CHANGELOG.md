# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/) 规范。

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
