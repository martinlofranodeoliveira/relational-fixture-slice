"""Dedicated, non-root Linux laboratory with direct-child-only signal authority.

/proc child IDs are a bounded cleanup veto, never authority to open a pidfd or
signal a process. No recursive process-tree discovery or descendant signaling.
"""

import ctypes
import os
from pathlib import Path
import pwd
import shutil
import signal
import subprocess
import tempfile
import time

import psycopg

from . import FixtureError

BIN = Path('/usr/lib/postgresql/17/bin')
MAX_CHILDREN = 64
MAX_CHILD_BYTES = 4096
MAX_LOG_BYTES = 64 * 1024
MAX_DIRECT = 2
ADOPT_TIMEOUT = 1.0
KILL_TIMEOUT = 2.0
POLL = 0.02


def children(pid=None):
    """Read only this process's direct/adopted child list, with finite bounds."""
    if pid is not None and pid != os.getpid():
        raise FixtureError('OWNERSHIP', 'descendant PID traversal is not supported')
    path = Path(f'/proc/{os.getpid()}/task/{os.getpid()}/children')
    try:
        with path.open('rb') as source:
            data = source.read(MAX_CHILD_BYTES + 1)
    except OSError as exc:
        raise FixtureError('OWNERSHIP', 'cannot verify the local child list') from exc
    parts = data.split()
    if len(data) > MAX_CHILD_BYTES or len(parts) > MAX_CHILDREN:
        raise FixtureError('OWNERSHIP', 'local child-list budget exceeded')
    if any(not p.isdigit() or len(p) > 10 for p in parts):
        raise FixtureError('OWNERSHIP', 'invalid local child list')
    return [int(p) for p in parts]


def exited(process):
    """Observe an owned, unreaped direct child without relinquishing ownership."""
    try:
        return os.waitid(os.P_PID, process.pid,
                         os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    except ChildProcessError as exc:
        raise FixtureError('OWNERSHIP', 'a direct child was reaped by another actor') from exc


class Owners:
    """Internal supervisor for at most two fixed direct commands.

    The caller is a dedicated process, with default SIGCHLD disposition and no
    other reaper. Popen objects remain retained until all signaling is finished.
    """

    def __init__(self):
        if (os.geteuid() == 0 or not hasattr(os, 'pidfd_open')
                or not hasattr(signal, 'pidfd_send_signal') or not hasattr(os, 'WNOWAIT')):
            raise FixtureError('PLATFORM', 'non-root Linux with pidfds and WNOWAIT is required')
        if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            raise FixtureError('OWNERSHIP', 'SIGCHLD must have its default disposition')
        if children():
            raise FixtureError('OWNERSHIP', 'dedicated process must start without children')
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:
            raise FixtureError('PLATFORM', 'cannot become a child subreaper')
        self.roots = []
        self.handles = {}
        self.logs = {}
        self.authority = True
        self.cleanup_safe = True
        self.statuses = ()
        self.adopted_statuses = []

    def start(self, args, log_path, env):
        if not self.authority or len(self.roots) >= MAX_DIRECT:
            raise FixtureError('OWNERSHIP', 'direct-child authority or budget unavailable')
        if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            raise FixtureError('OWNERSHIP', 'SIGCHLD disposition changed')
        log = Path(log_path).open('xb', buffering=0)
        try:
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       env=env, start_new_session=True, close_fds=True)
        except OSError as exc:
            log.close()
            raise FixtureError('CHILD_LAUNCH', 'fixed child could not be launched') from exc
        # Retain the Popen before any further fallible operation. With default
        # SIGCHLD and one reaper, this direct child cannot have its PID reused.
        self.roots.append(process)
        self.cleanup_safe = False
        self.logs[process.pid] = [log, 0]
        try:
            self.handles[process.pid] = os.pidfd_open(process.pid)
            os.set_blocking(process.stdout.fileno(), False)
        except OSError as exc:
            raise FixtureError('OWNERSHIP', 'cannot retain direct-child pidfd; cleanup must be verified') from exc
        return process

    def drain(self):
        # Pipes bound pending child output. Each poll reads at most 64 KiB per
        # direct child; each diagnostic file retains at most 64 KiB total.
        for process in self.roots:
            if process.stdout is None or process.stdout.closed:
                continue
            # start() may fail while configuring its pipe after retaining the
            # child. Never let cleanup block on a pipe left in blocking mode.
            if os.get_blocking(process.stdout.fileno()):
                continue
            try:
                block = os.read(process.stdout.fileno(), MAX_LOG_BYTES)
            except BlockingIOError:
                continue
            log, saved = self.logs[process.pid]
            keep = block[:max(0, MAX_LOG_BYTES - saved)]
            if keep:
                log.write(keep)
                self.logs[process.pid][1] += len(keep)

    def send(self, process, sig):
        if not self.authority or process not in self.roots:
            raise FixtureError('OWNERSHIP', 'direct-child signal authority unavailable')
        fd = self.handles.get(process.pid)
        if fd is None:
            raise FixtureError('OWNERSHIP', 'missing owned direct-child pidfd')
        try:
            signal.pidfd_send_signal(fd, sig)
        except ProcessLookupError:
            # An exited, unreaped direct child still belongs to us.
            pass

    def wait_roots(self, seconds):
        deadline = time.monotonic() + seconds
        while True:
            self.drain()
            live = [p for p in self.roots if not exited(p)]
            if not live or time.monotonic() >= deadline:
                return live
            time.sleep(min(POLL, max(0, deadline - time.monotonic())))

    def reap_adopted(self):
        # Signal authority is already revoked. Only nonblocking child waits are
        # used, with a deadline, iteration budget and retained-status budget.
        deadline = time.monotonic() + ADOPT_TIMEOUT
        for _ in range(256):
            remaining = children()
            if not remaining:
                return []
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return children()
            if pid:
                self.adopted_statuses.append(os.waitstatus_to_exitcode(status))
                if len(self.adopted_statuses) >= MAX_CHILDREN:
                    return children()
            elif time.monotonic() < deadline:
                time.sleep(min(POLL, max(0, deadline - time.monotonic())))
            if time.monotonic() >= deadline:
                return children()
        return children()

    def finish(self, graceful=5.0):
        if not self.authority:
            if not self.cleanup_safe:
                raise FixtureError('CLEANUP', 'previous shutdown did not prove child termination')
            return self.statuses
        failure = None
        try:
            for process in self.roots:
                self.send(process, signal.SIGINT)
            live = self.wait_roots(graceful)
            for process in live:
                self.send(process, signal.SIGKILL)
            if self.wait_roots(KILL_TIMEOUT):
                failure = 'an owned direct child did not terminate before the shutdown deadline'
        except BaseException as exc:
            failure = f'shutdown observation failed ({type(exc).__name__})'
        finally:
            # No direct child has been reaped above. Close every signal handle
            # before any wait that consumes a status. No later signaling exists.
            self.authority = False
            for fd in self.handles.values():
                os.close(fd)
            self.handles.clear()
        codes = []
        try:
            for process in self.roots:
                if not exited(process):
                    failure = failure or 'a direct child remains live'
                    continue
                try:
                    codes.append(process.wait(timeout=0))
                except subprocess.TimeoutExpired:
                    failure = failure or 'a direct-child status could not be consumed'
            if failure is None:
                remaining = self.reap_adopted()
                if remaining:
                    failure = 'direct/adopted children remain after the bounded shutdown wait'
            if failure is None and children():
                failure = 'the final local child-list check was not empty'
        except BaseException as exc:
            failure = failure or f'child verification failed ({type(exc).__name__})'
        finally:
            for process in self.roots:
                if process.stdout is not None:
                    process.stdout.close()
            for log, _ in self.logs.values():
                log.close()
            self.logs.clear()
        self.statuses = tuple(codes)
        self.cleanup_safe = failure is None and len(codes) == len(self.roots)
        if not self.cleanup_safe:
            raise FixtureError('CLEANUP', failure or 'child termination remains uncertain')
        if any(code != 0 for code in (*self.statuses, *self.adopted_statuses)):
            raise FixtureError('CHILD_FAILED', 'a direct/adopted child returned a nonzero exit status')
        return self.statuses


class Lab:
    def __init__(self):
        self.root = None
        self.owner = None
        self.connections = []
        self.versions = {}
        self.closed = False

    def __enter__(self):
        try:
            self.owner = Owners()
            # No TemporaryDirectory finalizer: uncertain shutdown must preserve
            # the namespace rather than delete data still possibly in use.
            self.root = Path(tempfile.mkdtemp(prefix='rfs-'))
            self.env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.root), 'TMPDIR': str(self.root),
                        'LC_ALL': 'C', 'LANG': 'C'}
            for tool in ('postgres', 'initdb'):
                log = self.root / f'{tool}-version.log'
                self.command([str(BIN / tool), '--version'], log)
                text = log.read_text(encoding='utf-8').strip()
                if '(PostgreSQL) 17.' not in text:
                    raise FixtureError('VERSION', 'PostgreSQL 17 tools required')
                self.versions[tool] = text
            for name in ('source', 'target'):
                base = self.root / name
                base.mkdir(mode=0o700)
                (base / 'socket').mkdir(mode=0o700)
                self.command([str(BIN / 'initdb'), '-D', str(base / 'data'), '-A', 'trust',
                              '--no-locale', '--encoding=UTF8'], base / 'initdb.log')
            for name in ('source', 'target'):
                base = self.root / name
                self.owner.start([str(BIN / 'postgres'), '-D', str(base / 'data'),
                                  '-k', str(base / 'socket'), '-h', '',
                                  '-c', 'shared_buffers=16MB', '-c', 'max_connections=12',
                                  '-c', 'unix_socket_permissions=0700', '-c', 'autovacuum=off',
                                  '-c', 'max_worker_processes=0', '-c', 'jit=off',
                                  '-c', 'log_min_messages=fatal',
                                  '-c', 'log_min_error_statement=panic',
                                  '-c', 'statement_timeout=5000'], base / 'server.log', self.env)
            for name in ('source', 'target'):
                deadline = time.monotonic() + 15
                while True:
                    self.owner.drain()
                    if any(exited(p) for p in self.owner.roots):
                        raise FixtureError('STARTUP', 'a private postmaster exited during startup')
                    try:
                        connection = self.connect(name)
                        setattr(self, name, connection)
                        self.versions[name] = connection.execute('SHOW server_version').fetchone()[0]
                        break
                    except psycopg.OperationalError:
                        if time.monotonic() >= deadline:
                            raise FixtureError('STARTUP', f'{name} did not accept private socket connections')
                        time.sleep(0.05)
            return self
        except BaseException as exc:
            self.__exit__(type(exc), exc, exc.__traceback__)
            raise

    def command(self, args, log_path):
        process = self.owner.start(args, log_path, self.env)
        deadline = time.monotonic() + 30
        while not exited(process):
            self.owner.drain()
            if time.monotonic() >= deadline:
                try:
                    self.owner.finish(0)
                except FixtureError as exc:
                    if exc.code != 'CHILD_FAILED':
                        raise
                raise FixtureError('CHILD_TIMEOUT', 'fixed PostgreSQL command exceeded 30 seconds')
            time.sleep(POLL)
        self.owner.finish(0)
        self.owner = Owners()

    def connect(self, name):
        if name not in ('source', 'target'):
            raise FixtureError('INPUT', 'unknown private cluster')
        self.connections = [c for c in self.connections if not c.closed]
        if len(self.connections) >= 12:
            raise FixtureError('LAB_LIMIT', 'laboratory connection budget exceeded')
        connection = psycopg.connect(host=str(self.root / name / 'socket'), dbname='postgres',
                                     user=pwd.getpwuid(os.geteuid()).pw_name, password='', passfile='/dev/null',
                                     sslmode='disable', gssencmode='disable', connect_timeout=1,
                                     options='-c statement_timeout=5000', autocommit=True)
        self.connections.append(connection)
        return connection

    def __exit__(self, exc_type, exc, traceback):
        if self.closed:
            return False
        self.closed = True
        for connection in self.connections:
            connection.close()
        self.connections.clear()
        stop_error = None
        if self.owner is not None and self.owner.authority:
            try:
                self.owner.finish()
            except FixtureError as error:
                stop_error = error
        safe = self.owner is None or self.owner.cleanup_safe
        if not safe:
            raise FixtureError('CLEANUP',
                               f'private namespace preserved at {self.root}; child termination is uncertain. '
                               'Dispose of the enclosing isolated namespace before removing its data; '
                               'no descendant signaling or automatic recovery is attempted') from stop_error
        if self.root is not None:
            try:
                shutil.rmtree(self.root)
            except OSError as error:
                raise FixtureError('CLEANUP', f'children stopped, but private files remain at {self.root}') from error
        if stop_error is not None:
            if exc is None:
                raise stop_error
            exc.add_note(str(stop_error))
        return False
