"""Behavioral tests. Set TMP/TEMP/TMPDIR to keep test artifacts in a chosen directory."""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

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


if __name__ == '__main__':
    unittest.main()
