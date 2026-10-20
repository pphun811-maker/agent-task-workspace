# Agent Task Workspace：给 agent 干杂活的独立任务目录

一个共用工作区，每个独立任务一个文件夹。同一任务持续复用，避免代码、下载材料、截图、报告和临时文件混在一起。

**v0.2.0 新增：整个工作区可搬家、只读查询历史任务、按任务 ID 复用，以及有备份的显式元数据升级。**

工作区可以叫任何名字，放在任何盘符或操作系统路径下。它是文件组织约定，不是权限沙箱，也不会自动配置 hook。

## 安装

需要 Python 3.10 或更新版本，只用标准库，不需要 pip 安装依赖。部分系统需要将命令中的 `python` 换成 `python3`。

1. 将本仓库内容放在你选定工作区的 `.agents/skills/agent-task-workspace/` 下，确保里面直接包含 `SKILL.md` 和 `scripts/`。
2. 从**工作区根目录**执行：

   ```text
   python .agents/skills/agent-task-workspace/scripts/workspace.py init --root . --write-instructions
   ```

   它创建 `.agent-workspace.json` 标记，并向现有 `AGENTS.md` 追加引用，不覆盖原指令。重复执行不会重复追加；遇到配置冲突会拒绝覆盖。默认任务容器叫 `agent-work`，初始化时可用 `--tasks-dir jobs` 改名。
3. 在该工作区新开聊天，让 agent 做下面的实际验收。

如果你的工具不读取 `AGENTS.md`，请把引用加到它支持的持久工作区指令中。某些工具只加载项目根目录，不向父级查找；单独打开子项目时，需要额外的条件引用。**脚本会找父级标记，不代表宿主会自动加载父级指令。**

可以把下面的要求发给其他 agent：

> 请为这个已启用 Agent Task Workspace 的工作区配置持久指令：仅当工作目录等于此工作区根目录，或位于其子目录时，开始文件工作前直接读取根目录的 AGENTS.md 和本 skill 的 SKILL.md。引用实际路径，不复制规则正文，不影响其他工作区；使用你明确支持的加载方式，保留现有配置。如果已经自动加载，不必重复配置。不要扫描应用安装包或历史聊天来寻找机制；不确定就说明限制。配置完成后实际创建和复用目录验收，不要把“当前聊天读过规则”当成持久配置已经验证。

## 日常行为

- agent 自主判断需不需要落盘；纯问答、只读检查不创建空目录。
- 首次需要任务文件时，运行 `create` 分配唯一目录；同一任务后续运行 `reuse` 验证并复用。
- 可控的代码、输入副本、脚本、下载、日志、截图、构建产物、缓存和临时文件都放在任务目录里。明确指定工具工作目录和输出路径。
- 保留用户任务涉及的已有项目原位修改、明确指定路径、品牌公用配置和记忆、共享规则维护等例外；不扩展宿主环境或记忆权限。
- 分配失败就报告具体命令、路径和原始错误，停止依赖该目录的写入。不自动改 ACL、不绕过沙箱、不扩大权限调查。
- 不保证文件系统隔离，不阻止宿主应用自身的内部写入，也不保证所有 agent 产品都原生支持自动加载。

## 跨聊天寻回任务

用户明确要求继续旧任务、但没给路径时，可以只读查询候选：

```text
python .agents/skills/agent-task-workspace/scripts/workspace.py list --root . --agent codex --limit 10
```

默认只返回任务名、agent、任务 ID、创建时间、当前目录和元数据版本，不读取任务文件内容，不列出里面的文件名。默认最多扫描任务容器下 1000 个直接条目；检查 `scan_complete` 和 `warnings`，有歧义时让用户选择，不自动接管最新任务。可按需设置 `--scan-limit`，上限 100000。

确定任务后，不需要记住完整目录：

```text
python .agents/skills/agent-task-workspace/scripts/workspace.py reuse --root . --agent codex --task-id "已确认的任务ID"
```

ID 不存在、重复、扫描不完整或有无效条目时，按 ID 复用会拒绝执行；已知目录仍可直接传 `--directory`。agent 名称仍精确匹配，跨品牌接手不自动发生。

## 搬家与升级

新版根标记保存工作区 ID，任务元数据保存该 ID 和相对目录；对外仍返回绝对路径。把整个工作区搬到别处后，在新根目录按任务 ID 复用即可，旧聊天中保存的绝对路径不会自动更新。复制工作区会保留同一身份，实际使用哪份副本由明确选择的根目录决定；不提供同步和冲突合并。

升级已有安装时先停止写入、备份 skill，并保持原引用路径。替换脚本后，执行显式升级：

```text
python .agents/skills/agent-task-workspace/scripts/workspace.py upgrade --root . --backup-dir "agent-work/metadata-upgrade-backup"
```

备份目录必须是尚不存在的新目录。命令先校验所有被扫描的任务元数据，备份原始字节，再迁移根标记和旧任务元数据；不搬动任务文件、不改 ACL。遇到可捕获的写入错误，会回滚已改元数据。进程被强行结束或断电时仍可能需要手动恢复。

最早的工作区专用 PowerShell 版本没有根标记，升级时须明确加 `--adopt-legacy`。没有 `workspace.json` 的目录不迁移，例如独立的权限修复备份。旧版绝对路径仍须在原位置匹配，因此要先升级，再搬家。

备份内附 `restore-workspace.py` 和清单，可独立恢复：

```text
python "agent-work/metadata-upgrade-backup/restore-workspace.py" restore --root . --backup-dir "agent-work/metadata-upgrade-backup"
```

恢复需要仍在原工作区位置，且升级后的元数据没有被再次修改、没有新增或删除受管任务；不满足就拒绝覆盖。备份仅恢复元数据，不恢复任务内容和系统权限。保留好备份，不要上传到公开仓库。

其他 agent 若只引用同一份 skill，无需逐个修改配置。已有聊天应重新读取规则，推荐新开聊天刷新技能描述；旧路径保留时不需要重复安装。

具体命令、所有权检查、标记发现和已知限制见 [English README](README.md)；agent 执行时以 [SKILL.md](SKILL.md) 为准。

## 验收

让 agent 读取规则，用自己的名字创建任务目录，写入 `hello.txt`，使用脚本的 `reuse` 子命令复用同一目录，再写入 `world.txt`。核对两个文件和 `workspace.json` 的实际位置；在日常使用的沙箱模式下验收。

## 发布说明

仓库根目录本身就是 skill，附 MIT 许可证和 GitHub Actions 测试配置。发布这里的源码即可，不要包含真实任务文件、权限备份或聊天日志。这个版本不绑定旧工作区，不在普通任务中自动迁移元数据，也不提供自动清理、归档或 hook。

本地测试命令：

```text
python -B -m unittest discover -s tests -v
```

安装或新建工作区不会更改 Windows 权限。脚本在不同平台使用各自原生的绝对路径，不把某个用户的路径打包进发布文件。
