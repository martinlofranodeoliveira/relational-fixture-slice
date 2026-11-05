#!/usr/bin/env python3
"""No connection-string CLI: this executable owns only its two private clusters."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from fixture_slice import FixtureError
from fixture_slice.cluster import Lab
from fixture_slice.demo import run


def main():
    parser = argparse.ArgumentParser(description='Relational Fixture Slice development 0.1.0')
    commands = parser.add_subparsers(dest='command', required=True)
    demo = commands.add_parser('demo', help='run synthetic offline export/restore cases')
    demo.add_argument('--assert', dest='verify', action='store_true', help='also check the complete acceptance case inventory')
    demo.add_argument('--json', action='store_true', help='emit only the deterministic JSON report')
    args = parser.parse_args()
    try:
        with Lab() as lab:
            report = run(lab, lab.root, args.verify)
        if not args.json:
            print('Relational Fixture Slice — development 0.1.0')
            for case in report['cases']:
                print(f"{case['case']}: {case['rows']} rows; verified")
            for case in report['rejections']:
                print(f"{case['case']}: {case['code']}; rollback verified")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except (FixtureError, OSError) as exc:
        print(f'fixture-slice: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('fixture-slice: interrupted; owned children stopped', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
