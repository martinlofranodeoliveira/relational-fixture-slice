#!/usr/bin/env python3
"""Serial integration runner; never discovers an installed database."""

import json
import os
from pathlib import Path
import platform
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))

from fixture_slice.cluster import Lab, children
from ownership_cases import OwnershipTests
import support


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    ownership = runner.run(unittest.defaultTestLoader.loadTestsFromTestCase(OwnershipTests))
    if not ownership.wasSuccessful() or children():
        return 1
    with Lab() as lab:
        support.LAB = lab
        lab.source.execute((ROOT / 'sql/install.sql').read_text(encoding='utf-8'))
        print(json.dumps({'qualified_tools': lab.versions, 'python': platform.python_version(),
                          'psycopg': __import__('psycopg').__version__,
                          'image_digest': os.environ.get('RFS_IMAGE_DIGEST', 'not supplied; native-tool run')},
                         sort_keys=True), flush=True)
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_*.py')
        result = runner.run(suite)
    if children():
        raise RuntimeError('direct/adopted children remain after shutdown')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
