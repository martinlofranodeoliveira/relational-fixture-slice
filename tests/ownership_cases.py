"""Run before the PostgreSQL lab: real fixed helpers, no unrelated children."""

import os
from pathlib import Path
import shutil
import select
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fixture_slice import FixtureError
from fixture_slice.cluster import Lab, Owners, children, exited

HELPER = Path(__file__).parent / 'helpers' / 'owned_process.py'


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.owner = Owners()
        self.root = Path(tempfile.mkdtemp(prefix='rfs-owner-test-'))
        self.env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': str(self.root)}

    def tearDown(self):
        if self.owner.authority:
            try:
                self.owner.finish(0)
            except FixtureError:
                pass
        # Test orphans have a fixed, finite lifetime. Never signal an adopted
        # PID, and never remove the namespace before proving there are no children.
        deadline = time.monotonic() + 3
        for _ in range(256):
            if not children():
                shutil.rmtree(self.root)
                return
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                pid = 0
            if time.monotonic() >= deadline:
                break
            if not pid:
                time.sleep(0.02)
        self.fail(f'helper termination uncertain; namespace preserved at {self.root}')

    def start(self, mode):
        return self.owner.start([sys.executable, str(HELPER), mode], self.root / 'child.log', self.env)

    def await_exit(self, process):
        deadline = time.monotonic() + 3
        while not exited(process):
            self.owner.drain()
            if time.monotonic() >= deadline:
                self.fail('fixed helper did not exit before its test deadline')
            time.sleep(0.01)
        # WNOWAIT has not consumed the direct-child status.
        self.assertIsNone(process.returncode)

    def test_zero_status_and_bounded_diagnostic_output(self):
        process = self.start('zero')
        self.await_exit(process)
        self.assertEqual(self.owner.finish(0), (0,))
        self.assertEqual(process.returncode, 0)
        self.assertFalse(self.owner.authority)
        self.assertEqual(self.owner.handles, {})
        self.assertTrue(self.owner.cleanup_safe)
        self.assertEqual((self.root / 'child.log').stat().st_size, 65536)
        with self.assertRaises(FixtureError):
            self.owner.send(process, 0)

    def test_failed_fixed_command_is_not_reported_as_success(self):
        process = self.start('failure')
        self.await_exit(process)
        with self.assertRaises(FixtureError) as caught:
            self.owner.finish(0)
        self.assertEqual(caught.exception.code, 'CHILD_FAILED')
        self.assertEqual(process.returncode, 7)
        self.assertTrue(self.owner.cleanup_safe)
        self.assertFalse(self.owner.authority)

    def test_timeout_uses_only_the_owned_direct_pidfd(self):
        process = self.start('timeout')
        deadline = time.monotonic() + 3
        while (self.root / 'child.log').read_bytes() != b'ready\n':
            self.owner.drain()
            if time.monotonic() >= deadline:
                self.fail('timeout helper did not announce readiness')
            time.sleep(0.01)
        self.assertEqual(set(self.owner.handles), {process.pid})
        with self.assertRaises(FixtureError) as caught:
            self.owner.finish(0)
        self.assertEqual(caught.exception.code, 'CHILD_FAILED')
        self.assertEqual(process.returncode, -9)
        self.assertTrue(self.owner.cleanup_safe)
        self.assertEqual(children(), [])

    def test_uncertain_adopted_child_preserves_namespace_without_signal_authority(self):
        process = self.start('orphan')
        self.await_exit(process)
        self.assertEqual(set(self.owner.handles), {process.pid})
        (self.root / 'sentinel').write_text('preserve while a child may use this namespace', encoding='utf-8')
        lab = Lab()
        lab.root = self.root
        lab.owner = self.owner
        with patch('fixture_slice.cluster.ADOPT_TIMEOUT', 0.05):
            with self.assertRaises(FixtureError) as caught:
                lab.__exit__(None, None, None)
        self.assertEqual(caught.exception.code, 'CLEANUP')
        self.assertIn(str(self.root), str(caught.exception))
        self.assertTrue((self.root / 'sentinel').is_file())
        self.assertFalse(self.owner.cleanup_safe)
        self.assertFalse(self.owner.authority)
        self.assertEqual(self.owner.handles, {})

    def test_descendant_pid_list_is_not_an_authority_source(self):
        with self.assertRaises(FixtureError) as caught:
            children(os.getpid() + 1)
        self.assertEqual(caught.exception.code, 'OWNERSHIP')

    def test_failed_pipe_preparation_does_not_block_cleanup(self):
        with patch('fixture_slice.cluster.os.set_blocking',
                   side_effect=OSError('injected pipe configuration failure')):
            with self.assertRaises(FixtureError) as caught:
                self.start('timeout')
        self.assertEqual(caught.exception.code, 'OWNERSHIP')
        process = self.owner.roots[0]
        # Positive barrier: the helper has installed its SIGINT handler and
        # emitted its only output. The still-blocking pipe is now quiet.
        ready, _, _ = select.select([process.stdout], [], [], 3)
        self.assertTrue(ready, 'fixed helper readiness deadline')
        self.assertEqual(os.read(process.stdout.fileno(), 6), b'ready\n')
        self.assertTrue(os.get_blocking(process.stdout.fileno()))
        with self.assertRaises(FixtureError) as stopped:
            self.owner.finish(0)
        self.assertEqual(stopped.exception.code, 'CHILD_FAILED')
        self.assertEqual(process.returncode, -9)
        self.assertTrue(self.owner.cleanup_safe)
        self.assertFalse(self.owner.authority)
        self.assertEqual(children(), [])
