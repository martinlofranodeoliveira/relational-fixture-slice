"""Relational Fixture Slice, development version 0.1.0."""

__version__ = '0.1.0'


class FixtureError(Exception):
    """A bounded-operation failure with a stable category and diagnostic detail."""

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f'{code}: {detail}')
