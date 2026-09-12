# AI-Rules 镜像对比规范（所有 AI 智能体共享）

> 本规范属于「规则」层，四工具共享、只读。任何 AI 在处理「人设/规则/记忆」文件、需要核对真源与副本是否一致时，应按本规范调用对比脚本。

## 一、脚本位置

```
你的真源目录\_scripts\mirror.py
```

调用方式：**AI 在终端直接执行 Python 命令**（Owner 不手动操作，故无 .bat 入口）。

## 二、四个命令

| 命令 | 作用 | 是否改文件 |
|---|---|---|
| `py mirror.py compare` | 对比真源(Obsidian) vs 副本(WorkBuddy)，输出差异清单 | ❌ 不改任何文件 |
| `py mirror.py report` | 生成 `待裁决.md` 差异报告 | ✅ 只写报告文件 |
| `py mirror.py check` | 校验 AGENTS.md 索引 ↔ 规则文件是否一一对应 | ❌ 不改任何文件 |
| `py mirror.py backup` | 备份真源内容到 `_archive/备份-YYYY-MM-DD/`（同一天只一次） | ✅ 写备份（不碰真源） |

> 说明：脚本**无 `sync`/`apply` 命令**——增删改由 AI 按 `ai_rules_collaboration.md` 执行，脚本只做机械对比 + 校验 + 备份。
> 另：`compare`/`report`/`check` 运行前都会**自动先执行一次 backup**（同一天只备份一次），做回滚兜底。`compare` 和 `report` 还会**自动附带索引对齐校验结果**。

## 三、脚本会生成的文件（都在 `_scripts/` 目录内）

| 文件 | 何时生成 | 内容 |
|---|---|---|
| `_scripts/compare.log` | 每次运行自动追加 | 对比/备份日志 |
| `_scripts/待裁决.md` | 跑 `report` 时生成 | 差异/冲突报告（给 Owner 裁决） |
| `_archive/备份-YYYY-MM-DD/` | 每天第一次操作时 | 真源内容全量备份（回滚用） |

> 脚本**不写任何真源内容文件**（AGENTS.md、README、1-人设、2-规则、3-记忆、4-索引），只读它们。

## 四、调用铁律（务必遵守）

1. **脚本只做机械比对和备份，不做裁决。** 它用哈希对比，找出差异，但**无权改真源一个字、无权删除文件**。
2. **任何增删改，最终以 Owner 批准为准。** 你（AI）对规则/人设/记忆的改动只是「建议」，出现冲突时生成 `待裁决.md`，交 Owner 裁决。
3. **冲突时不要手动覆盖。** 发现真源与副本两边都改过且不同，先跑 `compare` 看差异，再跑 `report` 出报告给 Owner，不要擅自回改。
4. **触发时机**：每次你更新完规则/人设后，跑一次 `compare` 核对真源与副本是否一致；不一致则按协作规则执行增删改或报 Owner。

## 五、各 AI 的调用方式

| 工具 | 调用方式 |
|---|---|
| WorkBuddy | 用 Bash 工具执行 `py mirror.py compare` / `report` / `backup` |
| Trae | 在终端执行 `py mirror.py compare` / `report` / `backup` |
| ZCode | 在终端执行 `py mirror.py compare` / `report` / `backup` |
| 豆包工作 | 若无命令执行能力，由 Owner 指挥其他 AI 代跑 |

## 六、回滚机制

- 每天第一次操作前，脚本自动把真源内容备份到 `_archive/备份-昨天日期/`。
- 误操作后，可从对应日期的备份文件夹恢复原始文件。
- 备份排除 `_scripts` 和 `_archive` 自身，避免无限套娃。
