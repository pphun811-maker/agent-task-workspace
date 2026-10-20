#!/usr/bin/env python3
"""Portable task directories: Python 3.10+, standard library only."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import time
from uuid import uuid4

VERSION = '0.2.0'
MARKER = '.agent-workspace.json'
METADATA = 'workspace.json'
LOCK = '.agent-workspace.lock'
BEGIN = '<!-- agent-task-workspace:begin -->'
END = '<!-- agent-task-workspace:end -->'
MAX_METADATA = 65536


def checked_path(value):
    path = Path(os.path.abspath(os.fspath(value)))
    for item in reversed((path, *path.parents)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError(f'Symlink/reparse paths are not supported: {item}')
    return path


def read_bytes(path, max_bytes=MAX_METADATA):
    checked_path(path)
    with path.open('rb') as stream:
        content = stream.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f'Metadata exceeds {max_bytes} bytes: {path}')
    return content


def read_json(path, max_bytes=MAX_METADATA):
    value = json.loads(read_bytes(path, max_bytes).decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError(f'Expected a JSON object: {path}')
    return value


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def write_new_json(path, value):
    with path.open('xb') as stream:
        stream.write(json_bytes(value))


def atomic_bytes(path, content):
    temporary = path.with_name(f'.{path.name}-{uuid4().hex}.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_tasks_dir(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}', value):
        raise ValueError('tasks_dir must be a single portable directory name (1-48 letters/digits/_/-).')
    if re.fullmatch(r'(?i:con|prn|aux|nul|com[0-9]|lpt[0-9])', value):
        raise ValueError('tasks_dir must not be a Windows reserved name.')
    return value


def valid_id(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 256


def workspace(root_value=None, allow_legacy=False, tasks_dir='agent-work', ignore_lock=False):
    if root_value is not None:
        root = checked_path(root_value)
    else:
        current = checked_path(Path.cwd())
        root = next((p for p in (current, *current.parents) if (p / MARKER).exists()), None)
        if root is None:
            raise ValueError(f'No {MARKER} found. Initialize an explicitly chosen workspace first.')
    if not root.is_dir():
        raise ValueError(f'Workspace root is not an existing directory: {root}')
    if not ignore_lock and (root / LOCK).exists():
        raise ValueError('Workspace mutation is in progress or a stale lock exists; retry or review the lock manually.')
    if allow_legacy and not (root / MARKER).exists():
        config = {'schema_version': 1, 'tasks_dir': validate_tasks_dir(tasks_dir)}
    else:
        config = read_json(root / MARKER)
    version = config.get('schema_version')
    if version not in (1, 2):
        raise ValueError('Unsupported workspace marker schema_version.')
    if version == 2 and not re.fullmatch(r'[0-9a-f]{32}', str(config.get('workspace_id', ''))):
        raise ValueError('Invalid workspace_id in marker.')
    task_root = checked_path(root / validate_tasks_dir(config.get('tasks_dir')))
    return root, task_root, config


def get_root(explicit=None):
    root, task_root, _ = workspace(explicit)
    return root, task_root


@contextmanager
def mutation_lock(root):
    path = checked_path(root / LOCK)
    deadline = time.monotonic() + 5
    while True:
        try:
            stream = path.open('x', encoding='ascii')
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ValueError('Another workspace mutation is running or a stale lock exists; review it manually.') from None
            time.sleep(0.01)
    try:
        with stream:
            json.dump({'pid': os.getpid(), 'created_utc': datetime.now(timezone.utc).isoformat()}, stream)
        yield
    finally:
        path.unlink()


def instruction_block(root):
    skill = checked_path(Path(__file__).parent.parent / 'SKILL.md')
    try:
        location = skill.relative_to(root).as_posix()
        reference = f'`{location}` (relative to this workspace root, not the current directory)'
    except ValueError:
        reference = f'`{skill.as_posix()}`'
    return (
        f'{BEGIN}\n## Agent task directories\n\n'
        'This workspace is opted into Agent Task Workspace. Before file work, directly read '
        f'and follow {reference}. Do not rely solely on automatic skill selection. '
        'Use the workspace marker to identify the root; reuse the same task directory on follow-ups. '
        'The skill defines file-placement rules and exceptions for existing projects, explicit '
        f'destinations, shared agent configuration and memory.\n{END}\n'
    )


def initialize(root_value, tasks_dir='agent-work', write_instructions=False):
    root = checked_path(root_value)
    if not root.is_dir():
        raise ValueError('Choose an existing workspace directory; init does not create the root.')
    validate_tasks_dir(tasks_dir)
    checked_path(root / tasks_dir)
    target = checked_path(root / 'AGENTS.md')
    original = target.read_text(encoding='utf-8-sig') if write_instructions and target.exists() else ''
    block = instruction_block(root) if write_instructions else ''
    if write_instructions and (BEGIN in original or END in original):
        if original.count(BEGIN) != 1 or original.count(END) != 1 or block.strip() not in original:
            raise ValueError('Existing instruction block differs or is malformed; review it manually. No overwrite performed.')
    existing = None
    if (root / MARKER).exists():
        _, _, existing = workspace(root)
        if existing['tasks_dir'] != tasks_dir:
            raise ValueError('Workspace marker already exists with different settings; no overwrite performed.')
    with mutation_lock(root):
        marker = root / MARKER
        if not marker.exists():
            write_new_json(marker, {'schema_version': 2, 'tasks_dir': tasks_dir, 'workspace_id': uuid4().hex})
        if write_instructions and BEGIN not in original:
            with target.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(('\n\n' if original else '') + block)
    return {'root': str(root), 'tasks_dir': tasks_dir, 'instructions_written': write_instructions,
            'upgrade_required': existing is not None and existing['schema_version'] == 1}


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Missing creation timestamp.')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Creation timestamp must include a timezone.')
    return result


def normalize(root, task_root, config, directory):
    directory = checked_path(directory)
    if directory.parent != task_root or not directory.is_dir():
        raise ValueError(f'Requires an existing direct child of {task_root}')
    data = read_json(directory / METADATA)
    version = data.get('schema_version', data.get('schemaVersion'))
    if version == 2:
        relative = data.get('relative_directory')
        expected = f'{config["tasks_dir"]}/{directory.name}'
        if (config['schema_version'] != 2 or data.get('workspace_id') != config['workspace_id']
                or not isinstance(relative, str) or relative != expected
                or PurePosixPath(relative).is_absolute() or '..' in PurePosixPath(relative).parts):
            raise ValueError('Workspace ID or relative task location does not match.')
        # Reject mixed schemas rather than silently trusting obsolete absolute bindings.
        if any(k in data for k in ('directory', 'workspace_root', 'schemaVersion')):
            raise ValueError('Mixed task metadata schemas are not supported.')
        task_id, created = data.get('task_id'), data.get('created_utc')
    elif version == 1:
        if data.get('directory') != str(directory):
            raise ValueError('Legacy absolute location does not match; upgrade before moving the workspace.')
        if 'schema_version' in data:
            if data.get('workspace_root') != str(root):
                raise ValueError('Legacy workspace root does not match.')
            task_id, created = data.get('task_id'), data.get('created_utc')
        else:
            task_id, created = data.get('taskId'), data.get('createdUtc')
    else:
        raise ValueError('Unsupported task metadata schema.')
    if not valid_id(task_id) or not valid_id(data.get('agent')) or not isinstance(data.get('task'), str):
        raise ValueError('Invalid task identity or name.')
    timestamp(created)
    return {'schema_version': version, 'agent': data['agent'], 'task': data['task'],
            'task_id': task_id, 'created_utc': created, 'directory': str(directory)}


def scan(root, task_root, config, scan_limit=1000):
    if not 1 <= scan_limit <= 100000:
        raise ValueError('scan_limit must be between 1 and 100000.')
    tasks, warnings, complete, scanned = [], [], True, 0
    if not task_root.exists():
        return tasks, warnings, complete, scanned
    with os.scandir(task_root) as entries:
        for entry in entries:
            if scanned >= scan_limit:
                complete = False
                break
            scanned += 1
            try:
                directory = checked_path(entry.path)
                if not directory.is_dir() or not (directory / METADATA).exists():
                    continue
                tasks.append(normalize(root, task_root, config, directory))
            except (OSError, ValueError, UnicodeError) as error:
                warnings.append({'directory': entry.name, 'error': str(error)})
    return tasks, warnings, complete, scanned


def list_tasks(root_value=None, agent=None, limit=10, scan_limit=1000):
    if not 1 <= limit <= 1000:
        raise ValueError('limit must be between 1 and 1000.')
    root, task_root, config = workspace(root_value)
    tasks, warnings, complete, scanned = scan(root, task_root, config, scan_limit)
    ids = {}
    for task in tasks:
        ids[task['task_id']] = ids.get(task['task_id'], 0) + 1
    for identity, count in ids.items():
        if count > 1:
            warnings.append({'task_id': identity, 'error': 'Duplicate task ID; ID-only reuse will be refused.'})
    selected = [t for t in tasks if agent is None or t['agent'] == agent]
    selected.sort(key=lambda t: (timestamp(t['created_utc']), t['directory']), reverse=True)
    return {'tasks': selected[:limit], 'matched_tasks': len(selected), 'scan_complete': complete,
            'scanned_entries': scanned, 'warning_count': len(warnings), 'warnings': warnings[:20]}


def slug(value):
    return re.sub(r'[^a-z0-9_-]+', '-', value.lower()).strip('-_')[:32] or 'task'


def create(root_value, agent, task='task', task_id=None):
    root, task_root, config = workspace(root_value, ignore_lock=True)
    if config['schema_version'] != 2:
        raise ValueError('Run explicit upgrade with a backup directory before creating v0.2 tasks.')
    if not valid_id(agent) or (task_id is not None and not valid_id(task_id)):
        raise ValueError('Agent and task ID must be nonempty strings of at most 256 characters.')
    with mutation_lock(root):
        if read_json(root / MARKER) != config:
            raise ValueError('Workspace configuration changed; retry.')
        if task_id is not None:
            tasks, warnings, complete, _ = scan(root, task_root, config)
            if warnings or not complete:
                raise ValueError('Cannot establish task ID uniqueness: task scan has warnings or is incomplete.')
            if any(t['task_id'] == task_id for t in tasks):
                raise ValueError('Task ID already exists; use reuse for that task.')
        task_root.mkdir(exist_ok=True)
        now, unique = datetime.now(timezone.utc), uuid4().hex
        directory = task_root / f'{slug(agent)}-{now:%Y%m%d-%H%M%SZ}-{slug(task)}-{unique}'
        directory.mkdir()
        metadata = {'schema_version': 2, 'workspace_id': config['workspace_id'],
                    'agent': agent, 'task': task, 'task_id': task_id if task_id is not None else unique,
                    'created_utc': now.isoformat(), 'relative_directory': directory.relative_to(root).as_posix()}
        try:
            write_new_json(directory / METADATA, metadata)
        except Exception:
            (directory / METADATA).unlink(missing_ok=True)
            directory.rmdir()
            raise
    return {'directory': str(directory), 'task_id': metadata['task_id'], 'reused': False}


def reuse(root_value, agent, directory_value=None, task_id=None, scan_limit=1000):
    root, task_root, config = workspace(root_value)
    if directory_value is None:
        if not valid_id(task_id):
            raise ValueError('Pass --directory or --task-id.')
        tasks, warnings, complete, _ = scan(root, task_root, config, scan_limit)
        if not complete or warnings:
            raise ValueError('ID lookup is incomplete or has invalid entries; review list warnings or pass a known directory.')
        matches = [t for t in tasks if t['task_id'] == task_id]
        if len(matches) != 1:
            raise ValueError('Task ID is missing or ambiguous; no task adopted.')
        metadata = matches[0]
    else:
        metadata = normalize(root, task_root, config, directory_value)
    if metadata['agent'] != agent:
        raise ValueError('Agent does not match; cross-agent takeover is not implicit.')
    if task_id is not None and metadata['task_id'] != task_id:
        raise ValueError('Task ID does not match.')
    return {'directory': metadata['directory'], 'task_id': metadata['task_id'], 'reused': True}


def digest(content):
    return hashlib.sha256(content).hexdigest()


def upgrade(root_value, backup_value, adopt_legacy=False, tasks_dir='agent-work', scan_limit=1000):
    root, task_root, config = workspace(root_value, adopt_legacy, tasks_dir)
    backup = checked_path(backup_value)
    if backup.exists() or backup == root or backup == task_root:
        raise ValueError('Choose a new, nonexistent backup directory.')
    tasks, warnings, complete, _ = scan(root, task_root, config, scan_limit)
    if warnings or not complete:
        raise ValueError('Upgrade refused: invalid task metadata or incomplete scan. Run list and resolve warnings first.')
    identities = [t['task_id'] for t in tasks]
    if len(identities) != len(set(identities)):
        raise ValueError('Upgrade refused: duplicate task IDs.')
    new_config = dict(config, schema_version=2,
                      workspace_id=config.get('workspace_id', uuid4().hex))
    changes = []
    for task in tasks:
        if task['schema_version'] == 2:
            continue
        path = Path(task['directory']) / METADATA
        data = {k: task[k] for k in ('agent', 'task', 'task_id', 'created_utc')}
        data.update(schema_version=2, workspace_id=new_config['workspace_id'],
                    relative_directory=path.parent.relative_to(root).as_posix())
        changes.append((path, read_bytes(path), json_bytes(data)))
    marker = root / MARKER
    old_marker = read_bytes(marker) if marker.exists() else None
    if old_marker is None or config != new_config:
        changes.append((marker, old_marker, json_bytes(new_config)))
    if not changes:
        return {'root': str(root), 'upgraded_tasks': 0, 'changed': False, 'backup_directory': None}
    with mutation_lock(root):
        # Recheck snapshots after obtaining the lock; stop on concurrent changes.
        for path, before, _ in changes:
            if (read_bytes(path) if path.exists() else None) != before:
                raise ValueError('Workspace changed during upgrade planning; retry.')
        backup.mkdir(parents=True)
        records = []
        for index, (path, before, after) in enumerate(changes):
            name = f'{index:06d}.before'
            if before is not None:
                (backup / name).write_bytes(before)
            records.append({'path': path.relative_to(root).as_posix(), 'existed': before is not None,
                            'backup_file': name, 'before_sha256': digest(before) if before is not None else None,
                            'after_sha256': digest(after)})
        manifest = {'schema_version': 1, 'root': str(root), 'tasks_dir': config['tasks_dir'],
                    'managed_paths': sorted((Path(t['directory']) / METADATA).relative_to(root).as_posix() for t in tasks),
                    'state': 'prepared', 'records': records}
        write_new_json(backup / 'manifest.json', manifest)
        (backup / 'restore-workspace.py').write_bytes(Path(__file__).read_bytes())
        applied = []
        try:
            for path, before, after in changes:
                atomic_bytes(path, after)
                applied.append((path, before))
            manifest['state'] = 'completed'
            atomic_bytes(backup / 'manifest.json', json_bytes(manifest))
        except Exception as error:
            failures = []
            for path, before in reversed(applied):
                try:
                    if before is None:
                        path.unlink()
                    else:
                        atomic_bytes(path, before)
                except Exception as failure:
                    failures.append(str(failure))
            manifest['state'] = 'rollback_failed' if failures else 'rolled_back'
            atomic_bytes(backup / 'manifest.json', json_bytes(manifest))
            raise ValueError(f'Upgrade failed: {error}; rollback errors: {failures}; backup: {backup}') from error
    return {'root': str(root), 'upgraded_tasks': sum(t['schema_version'] == 1 for t in tasks),
            'changed': True, 'backup_directory': str(backup),
            'restore_script': str(backup / 'restore-workspace.py')}


def safe_relative(root, value):
    if not isinstance(value, str) or '\\' in value or ':' in value:
        raise ValueError('Invalid backup relative path.')
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(p in ('..', '.') for p in relative.parts) or not relative.parts:
        raise ValueError('Invalid backup relative path.')
    path = checked_path(root.joinpath(*relative.parts))
    if not path.is_relative_to(root):
        raise ValueError('Backup path escapes workspace.')
    return path


def restore(root_value, backup_value):
    root, backup = checked_path(root_value), checked_path(backup_value)
    manifest = read_json(backup / 'manifest.json', 32 * 1024 * 1024)
    if manifest.get('schema_version') != 1 or manifest.get('root') != str(root) or manifest.get('state') != 'completed':
        raise ValueError('Backup is not a completed upgrade for this exact workspace location.')
    task_root = checked_path(root / validate_tasks_dir(manifest.get('tasks_dir')))
    current = sorted(p.relative_to(root).as_posix() for p in task_root.glob(f'*/{METADATA}')) if task_root.exists() else []
    if current != manifest['managed_paths']:
        raise ValueError('Managed task set changed since upgrade; no restore performed.')
    records = manifest['records']
    planned = []
    for record in records:
        path = safe_relative(root, record['path'])
        if path != root / MARKER and (path.name != METADATA or path.parent.parent != task_root):
            raise ValueError('Backup target is not a workspace metadata file.')
        before_file = safe_relative(backup, record['backup_file'])
        before = read_bytes(before_file) if record['existed'] else None
        if before is not None and digest(before) != record['before_sha256']:
            raise ValueError('Backup bytes do not match checksum.')
        after = read_bytes(path)
        if digest(after) != record['after_sha256']:
            raise ValueError('Metadata changed since upgrade; no restore performed.')
        planned.append((path, before, after))
    with mutation_lock(root):
        current = sorted(p.relative_to(root).as_posix() for p in task_root.glob(f'*/{METADATA}')) if task_root.exists() else []
        if current != manifest['managed_paths'] or any(read_bytes(p) != after for p, _, after in planned):
            raise ValueError('Workspace changed during restore planning; no restore performed.')
        applied = []
        try:
            for path, before, after in reversed(planned):
                if before is None:
                    path.unlink()
                else:
                    atomic_bytes(path, before)
                applied.append((path, after))
            manifest['state'] = 'restored'
            atomic_bytes(backup / 'manifest.json', json_bytes(manifest))
        except Exception:
            for path, after in reversed(applied):
                atomic_bytes(path, after)
            raise
    return {'root': str(root), 'restored': True, 'restored_files': len(planned)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=VERSION)
    commands = parser.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('init')
    setup.add_argument('--root', required=True)
    setup.add_argument('--tasks-dir', default='agent-work')
    setup.add_argument('--write-instructions', action='store_true')
    for name in ('create', 'reuse', 'list'):
        command = commands.add_parser(name)
        command.add_argument('--root')
        command.add_argument('--agent', required=name != 'list')
        if name == 'create':
            command.add_argument('--task', default='task')
            command.add_argument('--task-id')
        else:
            command.add_argument('--scan-limit', type=int, default=1000)
            if name == 'reuse':
                command.add_argument('--task-id')
                command.add_argument('--directory')
            else:
                command.add_argument('--limit', type=int, default=10)
    for name in ('upgrade', 'restore'):
        command = commands.add_parser(name)
        command.add_argument('--root', required=True)
        command.add_argument('--backup-dir', required=True)
        if name == 'upgrade':
            command.add_argument('--adopt-legacy', action='store_true')
            command.add_argument('--tasks-dir', default='agent-work')
            command.add_argument('--scan-limit', type=int, default=1000)
    args = parser.parse_args()
    try:
        if args.command == 'init':
            result = initialize(args.root, args.tasks_dir, args.write_instructions)
        elif args.command == 'create':
            result = create(args.root, args.agent, args.task, args.task_id)
        elif args.command == 'reuse':
            result = reuse(args.root, args.agent, args.directory, args.task_id, args.scan_limit)
        elif args.command == 'list':
            result = list_tasks(args.root, args.agent, args.limit, args.scan_limit)
        elif args.command == 'upgrade':
            result = upgrade(args.root, args.backup_dir, args.adopt_legacy, args.tasks_dir, args.scan_limit)
        else:
            result = restore(args.root, args.backup_dir)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, ValueError, UnicodeError) as error:
        print(f'workspace: {error}\nNo permission repair or sandbox bypass attempted.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
