# Agent Task Workspace

One shared workspace for miscellaneous agent work. One directory per independent task.

[简体中文](README.zh-CN.md)

Give your agents a place to do small jobs without scattering scripts, downloads, screenshots and reports across a shared root. This skill lets agents decide when files are needed, then allocate and reuse a task directory. It works with any workspace name and any agent that can read Markdown instructions and run Python.

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

Successful reuse returns `reused: true` without changing metadata or allocating a new directory. Agent names match exactly. If `--root` is omitted, the script searches upward from the process working directory. Supplying `--root` still requires an initialized marker; it never opts in a project implicitly. Moving a workspace changes absolute metadata paths; old task directories require deliberate migration, not automatic adoption.

## Behavior and boundaries

- A new independent task/chat gets a unique directory. A follow-up reuses it. Pure questions and read-only checks need no empty folder.
- All controllable task files, including scripts, input copies, downloads, caches and temporary files, belong in that directory. Set tool working/output paths explicitly.
- Existing projects may be edited in place when requested. Explicit destinations, normal agent shared configuration/memory locations and requested shared-rule maintenance remain exceptions.
- Allocation failures report the original error and stop dependent writes. The skill does not investigate the host, repair permissions or bypass a sandbox automatically.
- Path and metadata checks prevent common mistakes, not hostile actors. Symlinks, Windows junctions and other reparse paths are deliberately rejected, including in ancestor components. Choose the physical path when an OS exposes a directory through a link (for example, `/private/tmp` rather than `/tmp` on macOS). Ownership metadata is not authentication. No cross-task confidentiality or OS write isolation is provided.
- Concurrent task allocations use exclusive UUID-named directories. Initialization and instruction updates should run once, not concurrently.

This is a portable successor to a workspace-specific skill. It intentionally uses a new marker and metadata schema; it does not silently adopt directories created by earlier scripts. Keep older configurations until existing tasks are finished; do not install two contradictory workspace rules at once.

## Acceptance test

Ask your agent to read the workspace instructions, allocate a directory with its own name, write `hello.txt`, run `reuse`, then write `world.txt` in the same directory. Check the actual files and `workspace.json`, not just the agent's claim. If your host has sandbox modes, run the test in the mode you intend to use.

An existing workspace can have different permissions on old and newly created children. Root-directory write success alone does not prove the task folder is writable. Report failures without changing ACLs as part of this skill.

## Tests and publishing

```sh
python -B -m unittest discover -s tests -v
```

Tests use temporary directories; set `TMP`, `TEMP` and/or `TMPDIR` to keep them inside a chosen task directory. The GitHub Actions workflow defines Python 3.10/3.13 runs on Windows, macOS and Linux; a workflow file is not evidence those runners have passed before publication.

The repository root is itself the installable skill. Publish the source files in this directory, including `LICENSE`, `tests/`, and `.github/`; do not publish allocated task folders, runtime markers, private logs or local verification artifacts. Runtime task directories are ignored at this repository's root by `.gitignore`. MIT licensed.
