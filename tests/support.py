import json
from pathlib import Path
import tempfile
import unittest

from fixture_slice import FixtureError
from fixture_slice.bundle import export_bundle, import_bundle
from fixture_slice.demo import clear_target, no_orphans

LAB = None
ROOT = Path(__file__).resolve().parents[1]


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.lab = LAB
        self.source, self.target = LAB.source, LAB.target
        self.temp = tempfile.TemporaryDirectory(prefix='cases-', dir=LAB.root)
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.reset()
        self.serial = 0

    def reset(self):
        for name in ('sample', 'bad', 'odd'):
            self.source.execute(f'DROP SCHEMA IF EXISTS {name} CASCADE')
        self.source.execute((ROOT / 'sql/demo_data.sql').read_text(encoding='utf-8'))
        clear_target(self.target)

    def export(self, seeds=None, cap=10000, **kwargs):
        self.serial += 1
        path = self.root / f'bundle-{self.serial}'
        report = export_bundle(self.source, 'sample', seeds or [{'table': 'task', 'pk': 100}], path, cap, **kwargs)
        return path, report

    def restore(self, path):
        result = import_bundle(self.target, 'restored', path)
        no_orphans(self.target)
        return result

    def reject(self, code, callback):
        with self.assertRaises(FixtureError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def manifest(self, path):
        return json.loads((path / 'manifest.json').read_text(encoding='utf-8'))

    def write_manifest(self, path, manifest):
        (path / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
