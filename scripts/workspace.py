#!/usr/bin/env python3
"""Allocate task directories in an opted-in workspace; Python 3.10+, no dependencies."""

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
from datetime import datetime, timezone
from uuid import uuid4

MARKER = '.agent-workspace.json'
METADATA = 'workspace.json'
BEGIN = '<!-- agent-task-workspace:begin -->'
END = '<!-- agent-task-workspace:end -->'


def checked_path(value):
    """Refuse symlinks and Windows reparse points in any existing component."""
    path = Path(os.path.abspath(os.fspath(value)))
    for item in reversed((path, *path.parents)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError(f'Symlink/reparse paths are not supported: {item}')
    return path


def read_json(path):
    checked_path(path)
    with path.open(encoding='utf-8-sig') as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f'Expected a JSON object: {path}')
    return value


def write_new_json(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def validate_tasks_dir(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}', value):
        raise ValueError('tasks_dir must be a single portable directory name (1-48 letters/digits/_/-).')
    if re.fullmatch(r'(?i:con|prn|aux|nul|com[0-9]|lpt[0-9])', value):
        raise ValueError('tasks_dir must not be a Windows reserved name.')
    return value


def get_root(explicit=None):
    if explicit:
        root = checked_path(explicit)
    else:
        current = checked_path(Path.cwd())
        root = next((p for p in (current, *current.parents) if (p / MARKER).exists()), None)
        if root is None:
            raise ValueError(f'No {MARKER} found. Initialize an explicitly chosen workspace first.')
    if not root.is_dir():
        raise ValueError(f'Workspace root is not an existing directory: {root}')
    config = read_json(root / MARKER)
    if config.get('schema_version') != 1:
        raise ValueError('Unsupported workspace marker schema_version.')
    task_root = checked_path(root / validate_tasks_dir(config.get('tasks_dir')))
    return root, task_root


def instruction_block(root):
    skill = checked_path(Path(__file__).parent.parent / 'SKILL.md')
    try:
        location = skill.relative_to(root).as_posix()
        reference = f'`{location}` (relative to this workspace root, not the current directory)'
    except ValueError:
        reference = f'`{skill.as_posix()}`'
    return (
        f'{BEGIN}\n'
        '## Agent task directories\n\n'
        'This workspace is opted into Agent Task Workspace. Before file work, directly read '
        f'and follow {reference}. Do not rely solely on automatic skill selection. '
        'Use the workspace marker to identify the root; reuse the same task directory on follow-ups. '
        'The skill defines file-placement rules and exceptions for existing projects, explicit '
        'destinations, shared agent configuration and memory.\n'
        f'{END}\n'
    )


def initialize(root_value, tasks_dir='agent-work', write_instructions=False):
    root = checked_path(root_value)
    if not root.is_dir():
        raise ValueError('Choose an existing workspace directory; init does not create the root.')
    validate_tasks_dir(tasks_dir)
    checked_path(root / tasks_dir)
    marker = root / MARKER
    config = {'schema_version': 1, 'tasks_dir': tasks_dir}
    # Preflight instruction conflicts before writing the marker.
    target = checked_path(root / 'AGENTS.md')
    original = target.read_text(encoding='utf-8-sig') if write_instructions and target.exists() else ''
    block = instruction_block(root) if write_instructions else ''
    if write_instructions and (BEGIN in original or END in original):
        if original.count(BEGIN) != 1 or original.count(END) != 1 or block.strip() not in original:
            raise ValueError('Existing instruction block differs or is malformed; review it manually. No overwrite performed.')
    if marker.exists():
        if read_json(marker) != config:
            raise ValueError('Workspace marker already exists with different settings; no overwrite performed.')
    else:
        write_new_json(marker, config)
    if write_instructions and BEGIN not in original:
        # Append only; retain all existing instructions. Preserve original bytes/BOM.
        with target.open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(('\n\n' if original else '') + block)
    return {'root': str(root), 'tasks_dir': tasks_dir, 'instructions_written': write_instructions}


def slug(value):
    value = re.sub(r'[^a-z0-9_-]+', '-', value.lower()).strip('-_')[:32]
    return value or 'task'


def create(root_value, agent, task='task', task_id=None):
    root, task_root = get_root(root_value)
    if not agent.strip():
        raise ValueError('Agent must not be empty.')
    if task_id is not None and not task_id.strip():
        raise ValueError('Task ID must not be empty.')
    task_root.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    unique = uuid4().hex
    directory = task_root / f'{slug(agent)}-{now:%Y%m%d-%H%M%SZ}-{slug(task)}-{unique}'
    directory.mkdir()  # Exclusive allocation; never use exist_ok for an individual task.
    metadata = {
        'schema_version': 1,
        'agent': agent,
        'task': task,
        'task_id': task_id if task_id is not None else unique,
        'created_utc': now.isoformat(),
        'workspace_root': str(root),
        'directory': str(directory),
    }
    try:
        write_new_json(directory / METADATA, metadata)
    except Exception:
        # Only clean files in the directory allocated by this invocation.
        (directory / METADATA).unlink(missing_ok=True)
        directory.rmdir()
        raise
    return {'directory': str(directory), 'task_id': metadata['task_id'], 'reused': False}


def reuse(root_value, agent, directory_value, task_id=None):
    root, task_root = get_root(root_value)
    directory = checked_path(directory_value)
    if directory.parent != task_root or not directory.is_dir():
        raise ValueError(f'Reuse requires an existing direct child of {task_root}')
    metadata = read_json(directory / METADATA)
    if (metadata.get('schema_version') != 1 or metadata.get('agent') != agent
            or metadata.get('workspace_root') != str(root)
            or metadata.get('directory') != str(directory)
            or not isinstance(metadata.get('task_id'), str) or not metadata['task_id']):
        raise ValueError('Workspace metadata, agent or location does not match.')
    if task_id is not None and metadata['task_id'] != task_id:
        raise ValueError('Task ID does not match.')
    return {'directory': str(directory), 'task_id': metadata['task_id'], 'reused': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('init', help='Opt in an existing workspace; never overwrite configuration.')
    setup.add_argument('--root', required=True)
    setup.add_argument('--tasks-dir', default='agent-work')
    setup.add_argument('--write-instructions', action='store_true', help='Append a reference block to AGENTS.md.')
    for name in ('create', 'reuse'):
        command = commands.add_parser(name)
        command.add_argument('--root', help='Explicit opted-in root; otherwise discover nearest ancestor marker.')
        command.add_argument('--agent', required=True)
        command.add_argument('--task-id')
        if name == 'create':
            command.add_argument('--task', default='task')
        else:
            command.add_argument('--directory', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'init':
            result = initialize(args.root, args.tasks_dir, args.write_instructions)
        elif args.command == 'create':
            result = create(args.root, args.agent, args.task, args.task_id)
        else:
            result = reuse(args.root, args.agent, args.directory, args.task_id)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, ValueError) as error:
        print(f'workspace: {error}\nNo permission repair or sandbox bypass attempted.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
