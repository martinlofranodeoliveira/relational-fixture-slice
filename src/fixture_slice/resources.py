"""Locate the two trusted SQL scripts in a checkout or normal venv install."""

from pathlib import Path
import sys

from . import FixtureError


_ALLOWED = frozenset({'install.sql', 'demo_data.sql'})


def read_sql(name):
    if name not in _ALLOWED:
        raise FixtureError('INSTALLATION', 'unknown trusted SQL resource')
    candidates = (
        Path(__file__).resolve().parents[2] / 'sql' / name,
        Path(sys.prefix) / 'share' / 'relational-fixture-slice' / 'sql' / name,
    )
    for path in candidates:
        if path.is_file():
            return path.read_text(encoding='utf-8')
    raise FixtureError('INSTALLATION', 'trusted SQL resources missing; use a checkout or normal virtual-environment install')
