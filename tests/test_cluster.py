import os
from pathlib import Path

from support import DatabaseCase


class ClusterTests(DatabaseCase):
    def test_private_nonroot_two_cluster_configuration(self):
        self.assertNotEqual(os.geteuid(), 0)
        directories = []
        for connection in (self.source, self.target):
            self.assertEqual(connection.execute('SHOW listen_addresses').fetchone()[0], '')
            self.assertEqual(connection.execute('SHOW shared_buffers').fetchone()[0], '16MB')
            self.assertEqual(connection.execute('SHOW statement_timeout').fetchone()[0], '5s')
            directory = Path(connection.execute('SHOW data_directory').fetchone()[0])
            self.assertTrue(directory.is_relative_to(self.lab.root))
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            directories.append(directory)
        self.assertNotEqual(*directories)
        self.assertTrue(self.lab.owner.authority)
        self.assertEqual(len(self.lab.owner.roots), 2)
        for process in self.lab.owner.roots:
            self.assertIsNone(process.returncode)
            self.assertIn(process.pid, self.lab.owner.handles)
