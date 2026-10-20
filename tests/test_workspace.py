"""Behavioral tests. Set TMP/TEMP/TMPDIR to keep test artifacts in a chosen directory."""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'workspace.py'
spec = importlib.util.spec_from_file_location('workspace', SCRIPT)
ws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='workspace-test-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / 'shared chores space'
        self.root.mkdir()
        ws.initialize(self.root)

    def test_create_and_reuse(self):
        result = ws.create(self.root, 'workbuddy', 'report', 'chat-1')
        folder = Path(result['directory'])
        (folder / 'hello.txt').write_text('hello', encoding='utf-8')
        resumed = ws.reuse(self.root, 'workbuddy', folder, 'chat-1')
        self.assertTrue(resumed['reused'])
        self.assertEqual(result['directory'], resumed['directory'])
        (folder / 'world.txt').write_text('world', encoding='utf-8')
        self.assertEqual({p.name for p in folder.iterdir()}, {'hello.txt', 'world.txt', 'workspace.json'})

    def test_parallel_same_task_never_collides(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: ws.create(self.root, 'agent', 'same-task'), range(24)))
        self.assertEqual(len({r['directory'] for r in results}), 24)
        self.assertTrue(all((Path(r['directory']) / 'workspace.json').is_file() for r in results))

    def test_wrong_agent_and_task_are_rejected(self):
        result = ws.create(self.root, 'my-agent', task_id='one')
        for agent, task_id in [('another-agent', 'one'), ('my-agent', 'two')]:
            with self.assertRaises(ValueError):
                ws.reuse(self.root, agent, result['directory'], task_id)

    def test_outside_or_nested_directory_rejected(self):
        result = ws.create(self.root, 'agent')
        nested = Path(result['directory']) / 'nested'
        nested.mkdir()
        for target in (self.base, nested):
            with self.assertRaises(ValueError):
                ws.reuse(self.root, 'agent', target)

    def test_tampered_metadata_rejected(self):
        result = ws.create(self.root, 'agent')
        metadata = Path(result['directory']) / 'workspace.json'
        value = ws.read_json(metadata)
        value['directory'] = str(self.base)
        metadata.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaises(ValueError):
            ws.reuse(self.root, 'agent', result['directory'])

    def test_init_preserves_instructions_and_is_idempotent(self):
        target = self.root / 'AGENTS.md'
        prefix = b'\xef\xbb\xbf# Existing instructions\r\nKeep this rule.\r\n'
        target.write_bytes(prefix)
        ws.initialize(self.root, write_instructions=True)
        once = target.read_bytes()
        ws.initialize(self.root, write_instructions=True)
        self.assertEqual(once, target.read_bytes())
        self.assertTrue(once.startswith(prefix))
        self.assertEqual(once.count(ws.BEGIN.encode()), 1)

    def test_init_refuses_conflicting_configuration(self):
        before = (self.root / ws.MARKER).read_bytes()
        with self.assertRaises(ValueError):
            ws.initialize(self.root, 'different-tasks')
        self.assertEqual(before, (self.root / ws.MARKER).read_bytes())

    def test_init_refuses_conflicting_instruction_block(self):
        (self.root / 'AGENTS.md').write_text(ws.BEGIN + '\nstale\n' + ws.END, encoding='utf-8')
        before = (self.root / 'AGENTS.md').read_bytes()
        with self.assertRaises(ValueError):
            ws.initialize(self.root, write_instructions=True)
        self.assertEqual(before, (self.root / 'AGENTS.md').read_bytes())

    def test_no_implicit_initialization(self):
        unrelated = self.base / 'unrelated-project'
        unrelated.mkdir()
        with self.assertRaises(FileNotFoundError):
            ws.create(unrelated, 'agent')
        self.assertEqual(list(unrelated.iterdir()), [])

    def test_custom_task_root_and_invalid_names(self):
        other = self.base / 'another workspace'
        other.mkdir()
        ws.initialize(other, 'jobs')
        result = ws.create(other, 'agent')
        self.assertEqual(Path(result['directory']).parent, other / 'jobs')
        for name in ('../escape', '/absolute', '.codex', 'CON', 'LPT1', ''):
            with self.assertRaises(ValueError):
                ws.validate_tasks_dir(name)

    def test_cli_discovers_root_through_nested_git_project(self):
        nested = self.root / 'nested-project' / 'src'
        nested.mkdir(parents=True)
        (nested.parent / '.git').mkdir()
        process = subprocess.run(
            [sys.executable, '-B', str(SCRIPT), 'create', '--agent', 'cli-agent'],
            cwd=nested, text=True, encoding='utf-8', capture_output=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(Path(result['directory']).parent, self.root / 'agent-work')

    def test_cli_error_has_no_side_effects(self):
        process = subprocess.run(
            [sys.executable, '-B', str(SCRIPT), 'create', '--root', str(self.base), '--agent', 'agent'],
            text=True, encoding='utf-8', capture_output=True,
        )
        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stdout, '')
        self.assertIn('No permission repair or sandbox bypass', process.stderr)
        self.assertFalse((self.base / 'agent-work').exists())

    def test_symlink_task_root_rejected(self):
        destination = self.base / 'outside'
        destination.mkdir()
        try:
            (self.root / 'agent-work').symlink_to(destination, target_is_directory=True)
        except OSError as error:
            self.skipTest(f'Host does not allow symlink creation: {error}')
        with self.assertRaises(ValueError):
            ws.create(self.root, 'agent')
        self.assertEqual(list(destination.iterdir()), [])

    def test_metadata_with_bom_is_readable(self):
        result = ws.create(self.root, 'agent')
        metadata = Path(result['directory']) / 'workspace.json'
        original = metadata.read_text(encoding='utf-8')
        metadata.write_text(original, encoding='utf-8-sig')
        self.assertTrue(ws.reuse(self.root, 'agent', result['directory'])['reused'])

    def test_unicode_workspace_and_portable_labels(self):
        root = self.base / '\u6742\u6d3b\u5de5\u4f5c\u533a'
        root.mkdir()
        ws.initialize(root)
        result = ws.create(root, 'Agent / One', '\u622a\u56fe : task')
        folder = Path(result['directory'])
        self.assertTrue(folder.name.startswith('agent-one-'))
        self.assertTrue(folder.name.isascii())
        self.assertTrue(ws.reuse(root, 'Agent / One', folder)['reused'])

    def test_nearest_opted_in_root_wins(self):
        child = self.root / 'independent-space'
        child.mkdir()
        ws.initialize(child, 'jobs')
        process = subprocess.run(
            [sys.executable, '-B', str(SCRIPT), 'create', '--agent', 'agent'],
            cwd=child, text=True, encoding='utf-8', capture_output=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(Path(json.loads(process.stdout)['directory']).parent, child / 'jobs')

    def legacy(self, camel=False, marker=True):
        if marker:
            (self.root / ws.MARKER).write_text(json.dumps({'schema_version': 1, 'tasks_dir': 'agent-work'}), encoding='utf-8')
        else:
            (self.root / ws.MARKER).unlink()
        folder = self.root / 'agent-work' / 'old-task'
        folder.mkdir(parents=True)
        data = {'agent': 'agent', 'task': 'legacy report', 'directory': str(folder)}
        if camel:
            data.update(schemaVersion=1, taskId='legacy-id', createdUtc='2026-10-20T10:00:00Z')
        else:
            data.update(schema_version=1, task_id='legacy-id', created_utc='2026-10-20T10:00:00Z', workspace_root=str(self.root))
        (folder / 'workspace.json').write_text(json.dumps(data), encoding='utf-8-sig')
        (folder / 'report.txt').write_bytes(b'original deliverable')
        return folder

    def test_v2_moves_and_reuses_by_id(self):
        result = ws.create(self.root, 'agent')
        moved = self.base / 'moved workspace'
        self.root.rename(moved)
        resumed = ws.reuse(moved, 'agent', task_id=result['task_id'])
        self.assertEqual(Path(resumed['directory']).parent, moved / 'agent-work')
        self.assertNotEqual(resumed['directory'], result['directory'])
        self.assertTrue(resumed['reused'])

    def test_copied_workspace_resolves_only_within_selected_root(self):
        result = ws.create(self.root, 'agent')
        copied = self.base / 'copy'
        shutil.copytree(self.root, copied)
        resumed = ws.reuse(copied, 'agent', task_id=result['task_id'])
        self.assertEqual(Path(resumed['directory']).parent, copied / 'agent-work')
        self.assertEqual(ws.reuse(self.root, 'agent', task_id=result['task_id'])['directory'], result['directory'])

    def test_foreign_workspace_id_rejected(self):
        result = ws.create(self.root, 'agent')
        path = Path(result['directory']) / 'workspace.json'
        data = ws.read_json(path)
        data['workspace_id'] = 'f' * 32
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            ws.reuse(self.root, 'agent', result['directory'])

    def test_relative_escape_and_wrong_location_rejected(self):
        result = ws.create(self.root, 'agent')
        path = Path(result['directory']) / 'workspace.json'
        original = ws.read_json(path)
        for relative in ('../outside', '/absolute', 'agent-work/wrong', 'agent-work/../outside'):
            path.write_text(json.dumps(dict(original, relative_directory=relative)), encoding='utf-8')
            with self.assertRaises(ValueError):
                ws.reuse(self.root, 'agent', result['directory'])

    def test_list_is_metadata_only_read_only_and_filters(self):
        first = ws.create(self.root, 'first', 'one')
        ws.create(self.root, 'second', 'two')
        (Path(first['directory']) / 'private-filename.txt').write_text('secret data', encoding='utf-8')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = ws.list_tasks(self.root, agent='first', limit=1)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(len(result['tasks']), 1)
        self.assertEqual(result['tasks'][0]['task_id'], first['task_id'])
        self.assertNotIn('private-filename', json.dumps(result))
        self.assertNotIn('secret data', json.dumps(result))

    def test_list_orders_by_creation_and_limits(self):
        first = ws.create(self.root, 'agent', 'first')
        second = ws.create(self.root, 'agent', 'second')
        path = Path(first['directory']) / 'workspace.json'
        data = ws.read_json(path)
        data['created_utc'] = '2000-01-01T00:00:00Z'
        path.write_text(json.dumps(data), encoding='utf-8')
        result = ws.list_tasks(self.root, limit=1)
        self.assertEqual(result['tasks'][0]['task_id'], second['task_id'])
        self.assertEqual(result['matched_tasks'], 2)

    def test_corrupt_metadata_reported_and_id_lookup_refuses(self):
        result = ws.create(self.root, 'agent')
        invalid = self.root / 'agent-work' / 'bad'
        invalid.mkdir()
        (invalid / 'workspace.json').write_text('{', encoding='utf-8')
        listing = ws.list_tasks(self.root)
        self.assertEqual(len(listing['warnings']), 1)
        with self.assertRaises(ValueError):
            ws.reuse(self.root, 'agent', task_id=result['task_id'])
        self.assertTrue(ws.reuse(self.root, 'agent', result['directory'])['reused'])

    def test_incomplete_scan_cannot_claim_unique_task(self):
        result = ws.create(self.root, 'agent')
        ws.create(self.root, 'agent')
        self.assertFalse(ws.list_tasks(self.root, scan_limit=1)['scan_complete'])
        with self.assertRaises(ValueError):
            ws.reuse(self.root, 'agent', task_id=result['task_id'], scan_limit=1)

    def test_duplicate_task_ids_refused(self):
        first = ws.create(self.root, 'agent', task_id='same')
        with self.assertRaises(ValueError):
            ws.create(self.root, 'another-agent', task_id='same')
        second = ws.create(self.root, 'agent')
        metadata = Path(second['directory']) / 'workspace.json'
        data = ws.read_json(metadata)
        data['task_id'] = 'same'
        metadata.write_text(json.dumps(data), encoding='utf-8')
        self.assertTrue(ws.list_tasks(self.root)['warnings'])
        with self.assertRaises(ValueError):
            ws.reuse(self.root, 'agent', task_id='same')
        self.assertTrue(ws.reuse(self.root, 'agent', first['directory'], 'same')['reused'])

    def test_legacy_read_is_compatible_but_create_requires_upgrade(self):
        folder = self.legacy()
        before = (folder / 'workspace.json').read_bytes()
        self.assertTrue(ws.reuse(self.root, 'agent', folder, 'legacy-id')['reused'])
        self.assertEqual(ws.list_tasks(self.root)['tasks'][0]['schema_version'], 1)
        with self.assertRaises(ValueError):
            ws.create(self.root, 'agent')
        self.assertEqual(before, (folder / 'workspace.json').read_bytes())

    def test_upgrade_moves_legacy_workspace_without_moving_files(self):
        folder = self.legacy()
        backup = self.base / 'backup'
        result = ws.upgrade(self.root, backup)
        self.assertEqual(result['upgraded_tasks'], 1)
        self.assertEqual((folder / 'report.txt').read_bytes(), b'original deliverable')
        self.assertEqual(ws.read_json(folder / 'workspace.json')['schema_version'], 2)
        moved = self.base / 'relocated'
        self.root.rename(moved)
        self.assertEqual(Path(ws.reuse(moved, 'agent', task_id='legacy-id')['directory']).parent, moved / 'agent-work')

    def test_explicit_local_powershell_adoption_and_restore(self):
        folder = self.legacy(camel=True, marker=False)
        before = (folder / 'workspace.json').read_bytes()
        backup = self.base / 'local-backup'
        ws.upgrade(self.root, backup, adopt_legacy=True)
        self.assertTrue(ws.reuse(self.root, 'agent', task_id='legacy-id')['reused'])
        process = subprocess.run(
            [sys.executable, '-B', str(backup / 'restore-workspace.py'), 'restore', '--root', str(self.root), '--backup-dir', str(backup)],
            text=True, encoding='utf-8', capture_output=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFalse((self.root / ws.MARKER).exists())
        self.assertEqual((folder / 'workspace.json').read_bytes(), before)

    def test_upgrade_is_idempotent(self):
        self.legacy()
        ws.upgrade(self.root, self.base / 'backup')
        result = ws.upgrade(self.root, self.base / 'unused')
        self.assertFalse(result['changed'])
        self.assertFalse((self.base / 'unused').exists())

    def test_upgrade_failure_rolls_back_exact_original_bytes(self):
        folder = self.legacy()
        original_marker = (self.root / ws.MARKER).read_bytes()
        original_metadata = (folder / 'workspace.json').read_bytes()
        real_atomic = ws.atomic_bytes
        failed = False
        def fail_once(path, content):
            nonlocal failed
            if path == self.root / ws.MARKER and not failed:
                failed = True
                raise OSError('simulated storage failure')
            return real_atomic(path, content)
        backup = self.base / 'backup'
        with patch.object(ws, 'atomic_bytes', side_effect=fail_once):
            with self.assertRaises(ValueError):
                ws.upgrade(self.root, backup)
        self.assertEqual((folder / 'workspace.json').read_bytes(), original_metadata)
        self.assertEqual((self.root / ws.MARKER).read_bytes(), original_marker)
        self.assertEqual(ws.read_json(backup / 'manifest.json')['state'], 'rolled_back')
        self.assertFalse((self.root / ws.LOCK).exists())

    def test_restore_refuses_modified_metadata(self):
        folder = self.legacy()
        backup = self.base / 'backup'
        ws.upgrade(self.root, backup)
        data = ws.read_json(folder / 'workspace.json')
        data['task'] = 'edited after upgrade'
        (folder / 'workspace.json').write_text(json.dumps(data), encoding='utf-8')
        before = (folder / 'workspace.json').read_bytes()
        with self.assertRaises(ValueError):
            ws.restore(self.root, backup)
        self.assertEqual((folder / 'workspace.json').read_bytes(), before)

    def test_restore_refuses_new_tasks(self):
        self.legacy()
        backup = self.base / 'backup'
        ws.upgrade(self.root, backup)
        ws.create(self.root, 'agent')
        with self.assertRaises(ValueError):
            ws.restore(self.root, backup)

    def test_oversized_metadata_is_bounded(self):
        result = ws.create(self.root, 'agent')
        (Path(result['directory']) / 'workspace.json').write_bytes(b' ' * (ws.MAX_METADATA + 1))
        self.assertTrue(ws.list_tasks(self.root)['warnings'])

    def test_read_commands_do_not_ignore_mutation_lock(self):
        with ws.mutation_lock(self.root):
            with self.assertRaises(ValueError):
                ws.list_tasks(self.root)

    def test_duplicate_ids_cannot_be_created_concurrently(self):
        def allocate(_):
            try:
                return ws.create(self.root, 'agent', task_id='shared-id')
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(allocate, range(4)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(len(ws.list_tasks(self.root)['tasks']), 1)

    def test_failed_restore_rolls_forward_without_losing_new_format(self):
        folder = self.legacy()
        backup = self.base / 'backup'
        ws.upgrade(self.root, backup)
        after_marker = (self.root / ws.MARKER).read_bytes()
        after_metadata = (folder / 'workspace.json').read_bytes()
        real_atomic = ws.atomic_bytes
        failed = False
        def fail_once(path, content):
            nonlocal failed
            if path == folder / 'workspace.json' and not failed:
                failed = True
                raise OSError('simulated restore failure')
            return real_atomic(path, content)
        with patch.object(ws, 'atomic_bytes', side_effect=fail_once):
            with self.assertRaises(OSError):
                ws.restore(self.root, backup)
        self.assertEqual((self.root / ws.MARKER).read_bytes(), after_marker)
        self.assertEqual((folder / 'workspace.json').read_bytes(), after_metadata)

    def test_restore_rejects_tampered_backup(self):
        self.legacy()
        backup = self.base / 'backup'
        ws.upgrade(self.root, backup)
        manifest = ws.read_json(backup / 'manifest.json')
        (backup / manifest['records'][0]['backup_file']).write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            ws.restore(self.root, backup)

    def test_invalid_legacy_metadata_aborts_before_backup_or_mutation(self):
        folder = self.legacy()
        path = folder / 'workspace.json'
        path.write_text('{broken', encoding='utf-8')
        before = (self.root / ws.MARKER).read_bytes()
        backup = self.base / 'should-not-exist'
        with self.assertRaises(ValueError):
            ws.upgrade(self.root, backup)
        self.assertFalse(backup.exists())
        self.assertEqual((self.root / ws.MARKER).read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
