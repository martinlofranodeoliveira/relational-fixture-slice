import copy

from fixture_slice import FixtureError
from fixture_slice.manifest import decode, encode, safe_path
from support import DatabaseCase


class ManifestTests(DatabaseCase):
    def test_typed_adversarial_mutations(self):
        path, _ = self.export()
        original = self.manifest(path)
        mutations = [
            lambda m: m.update(sql='DROP TABLE x'),
            lambda m: m.update(version=True),
            lambda m: m.update(total_rows=10001),
            lambda m: m['tables'][0].update(file='../outside.csv'),
            lambda m: m['tables'][0].update(bytes=True),
            lambda m: m['tables'][0].update(sha256='0'*63),
            lambda m: m['tables'][0]['columns'][0].update(type='text); SELECT 1'),
            lambda m: m['tables'][0]['columns'][0].update(not_null=1),
            lambda m: m['tables'][0].update(name='x'*64),
            lambda m: m['tables'][0]['columns'].append(copy.deepcopy(m['tables'][0]['columns'][0])),
            lambda m: m['tables'].reverse(),
            lambda m: m['tables'][0]['foreign_keys'][0].update(target_column='absent'),
        ]
        for mutation in mutations:
            changed = copy.deepcopy(original)
            mutation(changed)
            with self.subTest(changed=changed), self.assertRaises(FixtureError):
                encode(changed)
        self.assertEqual(decode(encode(original)), original)

    def test_duplicate_keys_nonfinite_and_manifest_size(self):
        for data in (b'{"version":1,"version":1}', b'{"x":NaN}', b'[' * 2000, b'x' * (1024*1024+1), b'\xff'):
            with self.subTest(prefix=data[:30]), self.assertRaises(FixtureError):
                decode(data)

    def test_parent_traversal_and_symlink_ancestors(self):
        with self.assertRaises(FixtureError):
            safe_path(self.root / '..' / 'outside')
        real = self.root / 'real'
        real.mkdir()
        link = self.root / 'link'
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(FixtureError):
            safe_path(link / 'bundle')
