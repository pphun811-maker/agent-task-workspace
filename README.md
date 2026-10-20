# Agent Task Workspace

One shared workspace for miscellaneous agent work. One directory per independent task.

[简体中文](README.zh-CN.md)

Give your agents a place to do small jobs without scattering scripts, downloads, screenshots and reports across a shared root. This skill lets agents decide when files are needed, then allocate and reuse a task directory. It works with any workspace name and any agent that can read Markdown instructions and run Python.

Version 0.2 adds movable workspace metadata, read-only task discovery, ID-based reuse, and explicit backed-up upgrades from v0.1 or the original PowerShell metadata format.

```text
your-workspace/
  AGENTS.md
  .agent-workspace.json
  .agents/skills/agent-task-workspace/
    SKILL.md
    scripts/workspace.py
    ...
  agent-work/
    codex-<utc>-report-<uuid>/
      workspace.json
      report.md
    workbuddy-<utc>-image-job-<uuid>/
      workspace.json
      image.png
```

## Install into a chosen workspace

Requires Python 3.10+; no pip packages, network calls, Node or PowerShell dependencies. Use `python3` instead of `python` where needed.

1. Download this repository and place its contents at `<workspace>/.agents/skills/agent-task-workspace/`. This folder must directly contain `SKILL.md` and `scripts/`.
2. From the workspace root, opt in and append an instruction reference:

   ```sh
   python .agents/skills/agent-task-workspace/scripts/workspace.py init --root . --write-instructions
   ```

   This creates `.agent-workspace.json` and appends a marked section to `AGENTS.md`. It preserves existing instructions and does not duplicate an identical section. Conflicting configuration is rejected rather than overwritten. Omit `--write-instructions` if you will configure your host yourself. Choose another single folder name with `--tasks-dir jobs` at initialization.

3. Open a new chat with the chosen workspace. Confirm your host actually loads the instruction reference, then run a create/reuse smoke test.

The allocator discovers the nearest ancestor marker, including across nested Git roots. **That does not make a host load parent instructions.** If your host only loads its project root, add a conditional reference using its supported mechanism: only for this workspace and its descendants, read the root's `AGENTS.md` and this `SKILL.md` before file work. Match real directory boundaries, not a loose string prefix. Do not apply the rule globally to unrelated projects.

Do not assume all hosts support `AGENTS.md` or have the same filename precedence. Use the actual host's persistent instructions. Installing a skill alone does not guarantee automatic activation. This repository installs no hooks and changes no ACLs or sandbox settings.

## Use

Create, then retain the returned absolute directory and task ID:

```sh
python .agents/skills/agent-task-workspace/scripts/workspace.py create --root . --agent codex --task weekly-report
```

Output is one JSON object with `directory`, `task_id`, and `reused: false`. On a follow-up, pass the known values:

```sh
python .agents/skills/agent-task-workspace/scripts/workspace.py reuse --root . --agent codex --directory "<returned-directory>" --task-id "<returned-task-id>"
```

Successful reuse returns `reused: true` without changing metadata or allocating a new directory. Agent names match exactly. If `--root` is omitted, the script searches upward from the process working directory. Supplying `--root` still requires an initialized marker; it never opts in a project implicitly.

## Find and resume a previous task

When the user asks to continue old work, list metadata candidates:

```sh
python .agents/skills/agent-task-workspace/scripts/workspace.py list --root . --agent codex --limit 10
```

The output includes task IDs, original names, agent names, timestamps, current absolute paths and metadata schema versions. It does not enumerate files inside task directories or read their content. Omit `--agent` for an explicitly requested workspace-wide search. `--limit` defaults to 10 (maximum 1000). The scan visits at most 1000 direct container entries by default; `--scan-limit` can be increased up to 100000. Check `scan_complete`: on an incomplete scan, results are the newest among the scanned candidates, not necessarily the whole workspace. Invalid or oversized metadata is reported in warnings (first 20, with a total `warning_count`); file reads are capped at 64 KiB per task marker.

Ask the user to choose if candidates are ambiguous. Then resume by ID:

```sh
python .agents/skills/agent-task-workspace/scripts/workspace.py reuse --root . --agent codex --task-id "<selected-task-id>"
```

ID lookup refuses duplicate IDs, scan warnings, incomplete scans, missing IDs, and mismatched agent names. A known `--directory` can still be used directly, with an optional ID check. Selection never transfers ownership between agents automatically.

## Move or copy a workspace

Schema 2 records a stable `workspace_id` in the root marker, and that ID plus a workspace-relative directory in each task marker. Runtime output still uses absolute paths. Move the whole workspace, then pass its new root and the existing task ID to `reuse`; there is no absolute metadata prefix to rewrite.

Copying a workspace preserves its identity. Reuse resolves only inside the root you select, not another copy on your machine. This is not synchronization, authentication, or conflict resolution. Old absolute paths remembered by a chat do not update themselves; resolve by task ID after moving. Do not rename the task container or individual task directories without a separate migration plan.

## Upgrade an existing installation

Stop active writers and back up your installed skill before replacing it. Keep the installation path if other agents already reference it; upgrade code in place instead of installing a second conflicting skill. Existing chats should explicitly reread the updated instructions; opening a new chat is recommended to refresh skill discovery metadata.

`init` never silently upgrades an existing v0.1 marker. Legacy task metadata remains readable at its original location, but creating new tasks in a schema-1 workspace requires an explicit upgrade:

```sh
python .agents/skills/agent-task-workspace/scripts/workspace.py upgrade --root . --backup-dir "agent-work/metadata-upgrade-backup"
```

The backup path must not exist. The command validates the bounded metadata scan, backs up original bytes, and replaces only workspace/task metadata. It does not move task content or alter ACLs. Invalid metadata, duplicate task IDs or incomplete scans abort before changing metadata. Repeat after a successful upgrade is a no-op. Caught write failures trigger rollback; a process kill or power loss can require manual recovery from the saved bytes. Inspect a stale `.agent-workspace.lock` only after confirming its writer has stopped.

For the original workspace-specific PowerShell installation that has no marker, explicitly add `--adopt-legacy` (and `--tasks-dir` if needed). Original camelCase metadata is supported when its absolute directory still matches. Directories without `workspace.json`, such as permission-repair backups, are left alone. Upgrade before moving legacy workspaces; mismatched old absolute locations are not adopted automatically.

Each completed upgrade provides `manifest.json`, original metadata files and a standalone copy of the allocator for restoration:

```sh
python "agent-work/metadata-upgrade-backup/restore-workspace.py" restore --root . --backup-dir "agent-work/metadata-upgrade-backup"
```

Restore requires the original workspace location, unchanged upgraded metadata and the same managed task set. It refuses after new tasks are created or metadata is edited, rather than overwriting newer work. The backup restores metadata bytes, not task content or OS permissions. Keep the backup private and do not commit it.

## Behavior and boundaries

- A new independent task/chat gets a unique directory. A follow-up reuses it. Pure questions and read-only checks need no empty folder.
- All controllable task files, including scripts, input copies, downloads, caches and temporary files, belong in that directory. Set tool working/output paths explicitly.
- Existing projects may be edited in place when requested. Explicit destinations, normal agent shared configuration/memory locations and requested shared-rule maintenance remain exceptions.
- Allocation failures report the original error and stop dependent writes. The skill does not investigate the host, repair permissions or bypass a sandbox automatically.
- Path and metadata checks prevent common mistakes, not hostile actors. Symlinks, Windows junctions and other reparse paths are deliberately rejected, including in ancestor components. Choose the physical path when an OS exposes a directory through a link (for example, `/private/tmp` rather than `/tmp` on macOS). Ownership metadata is not authentication. No cross-task confidentiality or OS write isolation is provided.
- Concurrent task allocations use exclusive UUID-named directories and a short-lived workspace mutation lock. Contention waits for up to five seconds; read-only commands report an active lock instead of inspecting a migration mid-flight. Initialization and instruction updates should run once, not concurrently. This is local-process coordination, not a distributed lock for cloud-sync folders.

Explicit upgrade is the only bulk metadata migration path. Regular list/reuse calls do not rewrite old metadata or claim unmanaged directories. No automatic cleanup, archiving, cross-agent takeover or hooks are included.

## Acceptance test

Ask your agent to read the workspace instructions, allocate a directory with its own name, write `hello.txt`, run `reuse`, then write `world.txt` in the same directory. Check the actual files and `workspace.json`, not just the agent's claim. If your host has sandbox modes, run the test in the mode you intend to use.

An existing workspace can have different permissions on old and newly created children. Root-directory write success alone does not prove the task folder is writable. Report failures without changing ACLs as part of this skill.

## Tests and publishing

```sh
python -B -m unittest discover -s tests -v
```

Tests use temporary directories; set `TMP`, `TEMP` and/or `TMPDIR` to keep them inside a chosen task directory. The GitHub Actions workflow defines Python 3.10/3.13 runs on Windows, macOS and Linux; a workflow file is not evidence those runners have passed before publication.

The repository root is itself the installable skill. Publish the source files in this directory, including `LICENSE`, `tests/`, and `.github/`; do not publish allocated task folders, runtime markers, private logs or local verification artifacts. Runtime task directories are ignored at this repository's root by `.gitignore`. MIT licensed.
