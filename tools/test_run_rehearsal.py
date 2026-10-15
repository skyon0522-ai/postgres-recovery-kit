"""Boundary tests for the wrapper; these do not simulate a successful database run."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import run_rehearsal as runner


class EntryPointTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.work = self.root / 'work'
        self.go = self.root / 'go'
        self.go.write_text('#!/bin/sh\nexit 1\n')
        self.go.chmod(0o700)
        self.pg = self.root / 'pg'
        self.pg.mkdir()
        for name in ('postgres', 'initdb', 'pg_ctl', 'createdb', 'psql'):
            target = self.pg / name
            target.write_text('#!/bin/sh\nexit 1\n')
            target.chmod(0o700)
        self.args = ['--output-dir', str(self.work), '--go', str(self.go), '--pg-bin', str(self.pg)]

    def rejected(self, args):
        with patch.object(runner, 'ROOT', self.source), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                runner.arguments(args)
        self.assertEqual(error.exception.code, 2)

    def test_help_needs_no_dependencies_or_output(self):
        command = subprocess.run([sys.executable, '-B', str(Path(runner.__file__)), '--help'],
                                 capture_output=True, text=True)
        self.assertEqual(command.returncode, 0)
        self.assertIn('--output-dir', command.stdout)
        self.assertFalse(self.work.exists())

    def test_existing_file_directory_and_dangling_link_preserved(self):
        for kind in ('file', 'directory', 'link'):
            output = self.root / kind
            if kind == 'file':
                output.write_bytes(b'keep')
            elif kind == 'directory':
                output.mkdir()
            else:
                output.symlink_to(self.root / 'missing')
            self.rejected(['--output-dir', str(output)])
            self.assertTrue(os.path.lexists(output))
        self.assertEqual((self.root / 'file').read_bytes(), b'keep')

    def test_checkout_overlap_rejected(self):
        for output in (self.source, self.source / 'new', self.root):
            self.rejected(['--output-dir', str(output)])

    def test_missing_go_and_missing_postgres_create_nothing(self):
        self.rejected(['--output-dir', str(self.work), '--go', str(self.root / 'missing')])
        self.rejected(['--output-dir', str(self.work), '--go', str(self.go), '--pg-bin', str(self.root)])
        with patch.object(runner.shutil, 'which', return_value=None):
            self.rejected(['--output-dir', str(self.work)])
        self.assertFalse(self.work.exists())

    def test_cache_rules_and_explicit_valid_paths(self):
        self.rejected(self.args + ['--offline'])
        self.rejected(self.args + ['--module-cache', str(self.source)])
        self.rejected(self.args + ['--module-cache', str(self.root)])
        cache = self.root / 'modules'
        cache.mkdir()
        with patch.object(runner, 'ROOT', self.source):
            options = runner.arguments(self.args + ['--module-cache', str(cache), '--offline'])
        self.assertEqual(options.module_cache, cache)
        self.assertFalse(self.work.exists())

    def test_child_failure_preserves_logs_and_exit_code(self):
        self.work.mkdir(mode=0o700)
        with patch.object(runner, 'ROOT', self.source):
            code = runner.run_process([sys.executable, '-c',
                                       'import sys; print("controlled failure"); sys.exit(7)'], self.work)
        self.assertEqual(code, 7)
        self.assertIn('controlled failure', (self.work / 'runner.stdout').read_text())
        self.assertTrue((self.work / 'runner.stderr').is_file())

    def test_sigterm_allows_owned_child_finally_cleanup(self):
        self.work.mkdir(mode=0o700)
        child_script = self.root / 'controlled_child.py'
        child_script.write_text('import os, pathlib, time\n'
                                f'root=pathlib.Path({str(self.root)!r})\n'
                                '(root/"started").write_text(str(os.getpid()))\n'
                                'try:\n'
                                '    while True: time.sleep(0.05)\n'
                                'finally:\n'
                                '    (root/"cleaned").write_text("owned child cleanup")\n')
        harness = self.root / 'harness.py'
        harness.write_text('import sys, signal\n'
                           f'sys.path.insert(0, {str(Path(runner.__file__).parent)!r})\n'
                           'import run_rehearsal as runner\n'
                           'signal.signal(signal.SIGTERM, runner.interrupt_runner)\n'
                           'try:\n'
                           f'    runner.run_process([sys.executable, {str(child_script)!r}], runner.Path({str(self.work)!r}))\n'
                           'except KeyboardInterrupt:\n'
                           '    raise SystemExit(130)\n')
        process = subprocess.Popen([sys.executable, '-B', str(harness)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        child_pid = None
        try:
            deadline = time.monotonic() + 5
            while not (self.root / 'started').exists():
                self.assertIsNone(process.poll())
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
            child_pid = int((self.root / 'started').read_text())
            process.terminate()
            self.assertEqual(process.wait(timeout=5), 130)
            self.assertEqual((self.root / 'cleaned').read_text(), 'owned child cleanup')
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if child_pid is not None:
                try:
                    os.killpg(child_pid, 9)
                except ProcessLookupError:
                    pass


if __name__ == '__main__':
    unittest.main()
