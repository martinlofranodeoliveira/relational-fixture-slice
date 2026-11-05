# Contributing

Development version 0.1.0. Keep changes original, small and aligned with the documented subset. Do not submit private client code, real records, credentials, telemetry or invented adoption/performance claims.

## Local check

Use non-root Linux, Python 3.11+ and PostgreSQL 17 tools in the Debian path. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
. .venv/bin/activate
python3 tests/run.py
python3 bin/fixture_slice.py demo --assert --json
```

Do not parallelize tests. Run them in a dedicated process with default SIGCHLD disposition, no unrelated children and no competing reaper. The lifecycle preflight uses fixed helpers before the two private PostgreSQL clusters start. Do not connect to an installed database. See docs/testing.md for environment qualification, pinned image identity and failure disposal.

For behavior changes, update docs/contract.md, add a regression whose expected result follows independently from the contract, and update both READMEs if user-visible. Manifest changes need an explicit format decision. Keep bundle SQL unsupported, source functions SECURITY INVOKER and COPY on STDIN/STDOUT. SQL installation data must remain available in both a checkout and normal virtual-environment package installation.

Test unsuccessful paths: rollback, missing rows, caps, hostile identifiers/metadata, resource ownership and no overwrite. Do not infer signal authority from numeric process-tree listings. Do not delete a datadir after uncertain child shutdown. An uncertain shutdown must report a preserved namespace, not claim arbitrary descendant cleanup. Avoid timing-based performance assertions; bounded timeout behavior is a lifecycle assertion, not a benchmark.

Keep examples synthetic and explicit. Ordinary reproducible non-sensitive bugs and changes belong in the repository. Vulnerabilities belong in [GitHub private vulnerability reporting](https://github.com/martinlofranodeoliveira/relational-fixture-slice/security/advisories/new), not public issues. General contact: [Lofrano Tecnologia](https://lofranotecnologia.com.br).
