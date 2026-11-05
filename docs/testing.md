# Testing and environment qualification

Run serially from the repository root as a non-root Linux user:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
. .venv/bin/activate
python3 tests/run.py
python3 bin/fixture_slice.py demo --assert --json
```

Python 3.11+ and `/usr/lib/postgresql/17/bin/{postgres,initdb}` are required. The runtime dependency is exactly `psycopg[binary]==3.3.8`. No execution result is claimed here. The runner invokes both tools' `--version`, rejects non-17 tools and reports actual server, Python and psycopg versions. Native runs mark image digest as not supplied unless the environment supplied RFS_IMAGE_DIGEST.

CI pins the PostgreSQL 17 bookworm image to:

```text
sha256:839fbb5a4942a7758dd93e18b42ea5649807491a0545b5eeeb8f0b8bb11857a5
```

It records this identity and the runtime versions rather than resolving a mutable tag on each run. Python and system packages are installed from configured repositories, so this is image identity plus version qualification, not a complete reproducible-build claim. The runtime lock contains resolver-derived wheel hashes verified against official PyPI metadata for Linux amd64/CPython3.11. System package repositories remain external preparation inputs. Root is used only for dependency/workspace preparation; tests and demo run as the unprivileged `postgres` account. There is no privileged container, host database/socket, publishing or deployment step.

## Serial suites

Before starting PostgreSQL, the runner exercises direct-child lifecycle management using fixed Python helper modes:

- A successful child emits more than the retained diagnostic budget; its real exit status is consumed and the log remains exactly 64 KiB.
- A child exits 7; shutdown cannot report success despite certain cleanup.
- A child announces readiness and ignores SIGINT; only its directly owned pidfd receives final SIGKILL, producing a checked nonzero status.
- A helper leaves a short-lived adopted child. A deliberately short observation budget must produce CLEANUP, preserve the namespace and revoke signal authority. The test subsequently waits nonblockingly for the helper's fixed natural exit before removing its test directory; it never signals the adopted PID.
- Attempts to use descendant /proc traversal are rejected.

These tests run without other children. They do not use recycled numeric PIDs as authority or attempt arbitrary descendant cleanup.

The database lab initializes exactly two fresh clusters under a mode-0700 root. Unix sockets are private, listen_addresses is empty, shared_buffers is 16MB, max_connections is 12, background workers/autovacuum are disabled and statement_timeout is 5s. No installed database is discovered.

Database regression/adversarial coverage includes:

- Exact forward PK sets for task, shared parents, project-only, null and two-node cycle cases; shared-edge reasons and duplicate seed suppression.
- Independent restored value/orphan SQL, including quotes, newline, Unicode, empty text, literal `\N`, SQL NULL, negative integer and boolean.
- Literal expected FK MATCH/actions/deferral/validation and NOT NULL flags, not round-trip equality alone.
- Composite keys, defaults, CHECK, unique/secondary indexes, RLS, identity, generated columns, domains, arrays, external/nondeferrable/unvalidated FKs, partitions and user triggers; internal FK triggers remain accepted.
- Quoted identifiers containing embedded quotes, spaces, punctuation and SQL-looking text, including FK names and references.
- Row-cap statement rollback, preservation of a previous plan after savepoint rollback, missing references/seeds and invalid Python input types.
- Byte cap, no failed publication, no sweep of unrelated stages and atomic no-overwrite behavior.
- Concurrent row update after snapshot, blocked ALTER TABLE and lock release after failure.
- Duplicate JSON keys, nonfinite/deep/oversized input, typed manifest attacks, traversal, symlinks, hardlinks, FIFOs, extra files, digest/count mismatch and nonempty target protection, including a collation-only schema.
- COPY null-marker semantics with standard_conforming_strings disabled on both incoming connections.
- Rehashed reference corruption rejected by actual FK checking; rollback in both absent-schema and preexisting-empty-schema cases; successful retry from the original bundle.
- Actual private-cluster configuration and a final empty direct/adopted child-list check.

The preserved SQL assertion files provide independent relational oracles. The demo also performs its own assertions and emits deterministic human/JSON output. Installed demo code does not depend on test-file availability.

## Failure handling

Default SIGCHLD disposition, no unrelated children and no competing reaper are required. Only direct unreaped child pidfds grant signal authority. Normal shutdown requires actual zero statuses and an empty final direct/adopted list.

Uncertain termination preserves the private namespace and reports CLEANUP. The process must not be reused as though cleanup succeeded. Dispose of the enclosing isolated container/namespace before removing preserved data. Native callers must arrange their own disposal boundary. The lab does not promise arbitrary descendant termination, cgroup isolation, hard disk/RSS quotas or recovery after SIGKILL/power loss.
