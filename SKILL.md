---
name: agent-task-workspace
description: Organize files in an explicitly enabled workspace for miscellaneous agent tasks. Create and reuse a separate directory per independent chat or task, keeping task files together while allowing requested edits to existing projects and access to shared agent configuration or memory.
---

# Agent Task Workspace

Use this skill only in a workspace explicitly enabled by the user or its workspace instructions. Do not enable it in unrelated repositories just because the skill is installed globally.

## Locate the workspace

The opted-in root contains `.agent-workspace.json`, created during installation. It defines `tasks_dir` (default `agent-work`). Find the nearest such marker by walking upward from the current working directory, including across nested Git project roots. Alternatively use an explicitly supplied `--root`. Resolve workspace-relative paths from this root, not from the current subdirectory. The skill installation directory is not necessarily the workspace root.

If the marker is missing, do not silently initialize an arbitrary project: explain that setup is needed. Read the root's applicable instructions before file work.

## Allocate and reuse

Decide whether files need to be saved. Pure conversation, read-only inspection, and work exclusively at exception locations do not require an empty task directory.

Before other task writes, run the bundled script with Python 3.10+ (standard library only). Resolve `scripts/workspace.py` relative to this SKILL.md:

```text
python <skill-directory>/scripts/workspace.py create --root <workspace-root> --agent <agent-name> --task <short-task-name>
```

Use the actual agent name, for example `codex`, `zcode`, or `workbuddy`. Store the returned absolute `directory` and `task_id` in the task context. Each independent chat or task gets its own directory. A follow-up in the same task reuses the directory, rather than allocating one per message. Independent child agents get separate directories unless collaboration explicitly requires sharing.

Validate a known directory before resuming:

```text
python <skill-directory>/scripts/workspace.py reuse --root <workspace-root> --agent <agent-name> --directory <known-directory> --task-id <known-task-id>
```

Preserve both values during context compaction and handoff. Retain `workspace.json`. Agent names must match exactly on reuse; cross-agent takeover is not implicit. Metadata is an ownership check, not authentication.

## Find a previous task

When the user explicitly asks to continue a previous task but has no path or ID, query only task metadata:

```text
python <skill-directory>/scripts/workspace.py list --root <workspace-root> --agent <agent-name> --limit 10
```

The bounded, read-only query returns names, IDs, creation times and current absolute directories; it does not list task files or read their contents. Check `scan_complete` and warnings. Do not silently choose the newest task or adopt a similarly named task. Ask the user to select when candidates are ambiguous. Never inspect other tasks' content to infer ownership. If no task can be identified, allocate a new directory rather than guessing.

Once the task is selected, `reuse` also accepts `--task-id <known-id>` without `--directory`. ID lookup stays within the selected workspace and fails on ambiguity, incomplete scans or invalid entries. A known directory can be used directly to avoid unrelated scan warnings.

Version 0.2 metadata stores a workspace ID and a relative directory. After moving a workspace, use its current root and task ID to obtain a new absolute directory. Do not follow stale absolute paths saved in old chat context. Copies retain the workspace identity; the selected root determines which copy is used. This does not synchronize copies or resolve simultaneous edits.

Legacy metadata remains readable in its original location. Upgrading metadata is a separately requested maintenance operation with backups; never run bulk upgrades implicitly during ordinary tasks. See the repository README for `upgrade` and restore commands.

## Keep task file operations together

- Work inside the assigned directory. This includes generated code, input copies, downloads, screenshots, logs, build outputs, reports, and controllable temporary files and caches, not just final deliverables. Create subdirectories as needed.
- Explicitly set tool working directories and output paths on each call. Configure child-process temporary/cache paths locally when supported. A previous `cd` may not persist. Do not globally redirect the user's environment or merely move final files back after working elsewhere.
- External reference material may be read. Place needed copies inside the task directory. Do not relocate existing material or modify other tasks' directories.
- Deliver absolute links to final files. Avoid saving secrets in metadata or reports.

Exceptions remain available within the task's authorization:

- Edit existing projects or files in place when the user's task calls for it, including building/testing where that project requires. Keep additional standalone reports and screenshots in the task directory.
- Follow a user's explicitly requested destination.
- Access agent-brand shared configuration, skills, caches, state and memory at their normal locations (for example `.codex`). Respect host-specific memory permissions. A dot-prefixed name alone is not an exception, and shared directories must not become a dump for task files.
- Maintain this skill and the opted-in workspace's shared instruction/configuration files in place when requested.

## Fail without expanding scope

If a tool cannot honor an output path, use a suitable alternative or report the concrete limitation. If directory allocation fails, report the command, target path and original error, then stop dependent file operations. Do not silently use a different workspace, bypass a sandbox, change ACLs, inspect application internals, or launch broad permission investigations. Permission repair is a separate task requiring authorization.

This skill supplies file-organization instructions and allocation checks. It does not install hooks, enforce an OS sandbox, control the host application's internal writes, or grant permissions. Loading workspace instructions depends on the host; do not claim universal automatic activation.
