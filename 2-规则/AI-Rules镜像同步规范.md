# AI-Rules 镜像对比规范（所有 AI 智能体共享）

> 本规范属于「规则」层，多工具共享、只读。任何 AI 在处理「人设/规则/记忆」文件、需要核对真源与副本是否一致时，应按本规范调用脚本。

## 一、脚本位置与配置

```
<项目>/_scripts/mirror.py      # 机械比对 + 校验 + 下发 + 备份
<项目>/_scripts/memindex.py    # 索引层：技能清单的生成与校验
<项目>/config.json             # 真源路径等配置（不入库；样板见 config.example.json）
```

配置项（`config.json`）：

| 键 | 必填 | 说明 |
|---|---|---|
| `source_dir` | ✅ | 真源文档目录（规则/人设/记忆 md 所在根目录），支持 `~` |
| `skills_dir` | ⬜ | 技能目录，供 `memindex.py` 扫描生成清单；默认 `~/.workbuddy/skills` |

调用方式：**AI 在终端直接执行 Python 命令**（Owner 不手动操作，故无 .bat 入口）。

> **启动前置校验**：`source_dir` 缺失或不可用时，脚本报错退出（exit 2）并指出配置文件位置 ——
> 不会静默跑到错误目录、也不会拖到中途才抛裸异常。

## 二、命令一览（v0.3.0）

| 命令 | 作用 | 是否改文件 |
|---|---|---|
| `python mirror.py compare` | 对比真源 vs 副本，输出三类差异清单 | ❌ 只读 |
| `python mirror.py report` | 生成 `待裁决.md` 差异报告 | ✅ 只写报告 |
| `python mirror.py check` | 两段校验：① AGENTS.md 总表 ↔ 规则文件；② `4-索引` 双链地图 ↔ 真源 md | ❌ 只读 |
| `python mirror.py backup` | 备份真源内容到 `_archive/备份-YYYY-MM-DD/`（同一天只一次） | ✅ 只写备份 |
| `python mirror.py sync [工具]` | **dry-run**：报告三类差异 | ❌ 只读 |
| `python mirror.py sync --apply [工具]` | **下发「仅真源有」**；inbox 模式特例覆盖「内容不同」 | ✅ 写副本 |
| `python mirror.py sync --apply --take-ob [工具]` | Owner 裁决「以真源为准」后，覆盖「内容不同」的唯一通道 | ✅ 写副本 |
| `python memindex.py check` | 技能清单 ↔ 技能目录 是否一致 | ❌ 只读 |
| `python memindex.py diff` | 打印将要写入的内容（dry-run） | ❌ 只读 |
| `python memindex.py gen` | 重建 `4-索引/技能清单.md` | ✅ 写真源（仅此一个文件） |

> - **命令白名单**：未知命令一律报错退出（exit 2），不会静默降级为 `compare`。
> - **备份范围**：只读命令（`compare` / `check`）**不触发备份**；写操作前自动备份（同一天只一次）。
> - **写后复核**：`sync --apply` 结束后自动重跑分类并打印复核结果。
> - `compare` / `report` 会自动附带索引对齐校验结果。

### 三种下发形态

| 形态 | 工具 | 行为 |
|---|---|---|
| **1:1 翻译下发** | WorkBuddy / Trae | 占位符 `{RULES_DIR}` 等翻译为工具本地路径后写入 |
| **inbox 直拷**（v0.2.0 新增） | ZCode | 真源文件原样保留子目录拷入 inbox，由 ZCode 自己归位；不翻译、不分类、不改名 |
| **N:1 拼接**（v0.2.0 弃用） | — | 旧版 ZCode 拼接单 AGENTS.md 方案，已被 inbox 取代 |

### sync 铁律

- **「仅真源有」**：自动下发（机械安全动作）
- **「内容不同」**：默认停手等 Owner 裁决。两处**显式例外**：
  1. **inbox 模式**自动覆盖（raw 副本过期就该重写）
  2. 显式给出 **`--take-ob`**（表示 Owner 已裁决「以真源为准」）
- **「仅副本有」**：一律停手（可能是自有副本或别处加工产物，需人工判断）

> `--take-ob` 不允许默认生效、不允许省略 `--apply` —— 必须两个标志同时显式写出，
> 防止「手滑覆盖」。它仍不碰「仅副本有」。

## 三、脚本生成的文件

| 文件 | 何时生成 | 内容 |
|---|---|---|
| `<项目>/_scripts/compare.log` | 每次运行自动追加 | 运行日志 |
| `<项目>/_scripts/待裁决.md` | 跑 `report` 或 `sync --apply` 时 | 差异/冲突报告（给 Owner 裁决） |
| `<项目>/_archive/备份-YYYY-MM-DD/` | 写操作当天第一次 | 真源内容全量备份（回滚用） |
| `<真源>/4-索引/技能清单.md` | 跑 `memindex.py gen` 时 | 技能索引（**勿手改**，由技能目录机械扫描生成） |

> 除 `4-索引/技能清单.md` 外，脚本**不写任何真源内容文件**，只读它们。
> 运行产物（日志/报告）与备份都落在**工程侧**（`<项目>/`），不落进真源 ——
> 真源只保留内容 md，这样它才能干净地被版本管理 / 同步。

## 四、调用铁律（务必遵守）

1. **脚本只做机械比对、校验与下发，不做裁决。** 它用哈希比对找差异，但**无权改真源一个字、无权删除文件**。
2. **任何增删改，最终以 Owner 批准为准。** 你（AI）对规则/人设/记忆的改动只是「建议」，出现冲突时生成 `待裁决.md`，交 Owner 裁决。
3. **冲突时不要手动覆盖。** 发现真源与副本两边都改过且不同，先跑 `compare` 看差异，再跑 `report` 出报告给 Owner，不要擅自回改。
4. **触发时机**：每次更新完规则/人设后，跑一次 `compare` 核对真源与副本是否一致；不一致则按协作规则执行增删改或报 Owner。

## 五、各 AI 的调用方式

| 工具 | 调用方式 |
|---|---|
| WorkBuddy | 用 Bash 工具执行 `python mirror.py <命令>` |
| Trae | 在终端执行 `python mirror.py <命令>` |
| ZCode | 在终端执行 `python mirror.py <命令>`（仅与 inbox 收件箱交互） |
| 豆包工作 | 若无命令执行能力，由 Owner 指挥其他 AI 代跑 |

## 六、回滚机制

- 写操作当天第一次，脚本自动把真源内容备份到 `_archive/备份-当天日期/`。
- 误操作后，可从对应日期的备份文件夹恢复原始文件。
- 备份排除 `_scripts` 和 `_archive` 自身，避免无限套娃。
- 手工重大改动前，应额外单独备份到 `_archive/备份-<原因>-YYYY-MM-DD/`。

## 七、ZCode 边界铁律（v0.2.0）

**`~/.zcode/` 下所有文件是 ZCode 自己的家务事，本体系永不触碰**：

- ❌ 不比对（inbox 外的 ZCode 内部文件均不在 `mirror.py` 比对范围）
- ❌ 不下发（我们的下发只到 inbox 收件箱为止）
- ❌ 不删除（即使看着像「废弃文件」，ZCode 自己有归档机制，体系不替它做决定）
- ❌ 不修改

**具体表现**：
- `TOOLS["zcode"]["inbox"]` 指向 `~/.zcode/workspace/default/inbox/`，所有下发目标都在它下面
- ZCode 归位后可能产生的产物（如 `~/.zcode/AGENTS.md`、`~/.zcode/cli/memories/...` 等）**不在 mirror.py 比对范围**
- ZCode 自己有备份机制（`_archive-YYYY-MM-DD/AGENTS.md.bak-XXXX` 等），体系不动它

## 八、双向遍历加固（v0.2.0）

`mirror.py build_pairs()` 在原有「真源侧规则目录遍历」基础上，增加**副本侧孤儿扫描**：

- 遍历副本 `rules_dir/` 下所有 `.md` 文件
- 对**真源任何位置都没有 + files 字段未改名映射**的文件生成 `(None, dst, tool, None)` 伪 pair
- `compare()` 自然把这些归入「仅副本有」分支
- inbox 模式跳过此扫描（inbox 由 ZCode 自己整理，"副本有但真源无" 不等于孤儿）

**防误报机制**：
- 收集真源所有 `.md` 文件 basename 时，遍历 OB 根 + 所有子目录（不仅是 `2-规则/`）
- 收集 `files` 字段所有目标 basename，跳过「改名映射」（如 `USER.md → user_profile.md`）
