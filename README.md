# DB Drift Detective

Find application-behavior differences between **real SQLite and PostgreSQL**, then
reduce a failing dataset into a small, executable reproduction.

## What works

- A validated schema/operation JSON format with bound parameters.
- CREATE TABLE, seed inserts, SELECT, INSERT, UPDATE, and DELETE within a bounded DSL.
- Comparison of write acceptance, normalized error categories, affected row counts,
  query results, and final durable state.
- Ordered comparison only with a deterministic primary-key tie breaker; otherwise
  duplicate-preserving bag comparison.
- Seeded edge-case generation for null sorting, flexible typing, foreign keys,
  LIKE case sensitivity, embedded NUL text, historical Open WebUI JSON search, and compatible controls.
- Chunk-based row/operation reduction, final one-deletion checks, and two final
  repetitions of the reduced witness.
- Reproduction ZIPs with JSON cases, SQL templates and bindings, a runnable
  reproducer, and a compatibility regression test.
- A local FastAPI dashboard with paired outcomes, state tables, replay, reduction,
  cancellation, persistent history, and downloadable evidence.

## Run

```powershell
cd D:\db-drift-detective
.\run.ps1 serve
```

Open **http://127.0.0.1:8766**. CrashLab remains separately available on port 8765.
Useful demonstrations are already in the history, including a **500-row case
reduced to 2 rows and 1 query** with verified one-deletion minimality.

The dedicated PostgreSQL database is `driftlab`, accessed through its own
non-superuser role on `127.0.0.1:55432`. It shares the existing portable PostgreSQL
server with CrashLab, but uses a separate database and private credentials.
Physical server data remains under D:\crashlab\.data\postgres. No cloud is needed.

After reboot, start that server with:

```powershell
D:\crashlab\postgres.ps1 start
```

## CLI

```powershell
# Compare the complete built-in matrix, including passing controls
.\run.ps1 demo

# Inspect database readiness and versions
.\run.ps1 doctor

# Run a known difference, then its explicit-policy control
.\run.ps1 run cases\null_order.json
.\run.ps1 run cases\null_order_fixed.json

# Generate repeatable noise around a targeted compatibility witness
.\run.ps1 generate --family null_order --rows 500 --seed 7 --output D:\db-drift-detective\runs\large-case.json
.\run.ps1 reduce D:\db-drift-detective\runs\large-case.json

# Replay/export a report using its printed path
.\run.ps1 replay D:\db-drift-detective\runs\comparisons\RUN_ID\report.json
.\run.ps1 export D:\db-drift-detective\runs\comparisons\RUN_ID\report.json

# Tests against SQLite and the actual local PostgreSQL server
python -B -m unittest discover -s tests -v
```

Exit codes: 0 = compatible or expected demo/reduction/export success; 1 = observed
drift; 2 = configuration/harness error. A database rejection is recorded as an
operation outcome; a failed database connection is an experiment error.

## Example finding

With rows `(id=1, priority=NULL)` and `(id=2, priority=1)`, this logical operation
returns a different first row on the two engines when null placement is implicit:

```sql
SELECT id, priority FROM records ORDER BY priority ASC, id ASC LIMIT 1;
```

Adding an explicit `NULLS LAST` policy makes the built-in control agree. The
report preserves actual rows, SQL templates, bindings, engine versions, and a
stable finding signature so the behavior is independently inspectable.

## Export semantics

The ZIP contains `case.json`, `expected.json`, `report.json`, `sqlite.sql`,
`postgres.sql`, dialect-specific binding files, `reproduce.py`, and
`test_regression.py`.

- `reproduce.py` exits 0 when the saved behavior/finding is observed again.
- `test_regression.py` requires compatibility. It deliberately fails on an unfixed
  drift case, then passes after its explicit policy/schema/operation is corrected.
- SQL files are driver templates with separate bindings, not direct psql scripts.
- Private database credentials are excluded. The case and result data are included.
- Reproduction scripts require this project; set DRIFTLAB_ROOT if its checkout moves.

## Isolation and comparison policy

Each trial gets a fresh SQLite file and a generated `drift_<uuid>` PostgreSQL
schema. The PostgreSQL schema is dropped after evidence collection; snapshots and
SQL remain in the report. The tool never discovers or alters existing application
tables. Per-operation transactions let later steps continue after a rejected write.

SQLite foreign keys default to **enabled in the tool**. The foreign-key witness
explicitly disables them, and the report records that setting. INTEGER represents
each engine's native INTEGER; REAL maps to SQLite REAL / PostgreSQL DOUBLE PRECISION.
JSON maps to checked TEXT in SQLite and native JSON (not JSONB) in PostgreSQL. JSON values are supplied as serialized strings and normalized semantically in results. Numeric whole-valued floats and integers compare equally; strings remain distinct.
Error wording and engine-specific codes remain visible but canonical categories
are used for compatibility comparison.

## Practical limits

- Supported schemas: up to 4 tables, 10 columns each, exactly one primary key per
  table, INTEGER/TEXT/REAL/JSON, nullability, uniqueness, and earlier-table references. JSON cannot be a primary/unique key.
- Supported inputs: up to 1000 seed rows and 40 operations; scalar values are bounded.
- Predicates: eq/ne/gt/gte/lt/lte/is_null/not_null/like and a bounded JSON-array text search, combined with AND.
- No arbitrary SQL, joins, expressions, aggregates, migrations of live data,
  SQL rewriting, repository instrumentation, or universal compatibility guarantee.
- The generator creates known families with seeded noise; it is not a general SQL fuzzer.
- Reduction preserves the first finding's source, step ID, and kind. Schema remains
  fixed. Verified minimality concerns deletion of one remaining row or operation,
  not a globally smallest proof or an independently established root cause.
- The dashboard runs one job at a time with at most 6 queued/active jobs. Evidence
  appears after completion. Interrupted history is marked for explicit replay.
- Rendering limits state tables to 100 rows; full data remains in the export.

## Project map

| File | Responsibility |
| --- | --- |
| `driftlab/model.py` | Strict DSL validation and deterministic-order requirements |
| `driftlab/sql.py` | Dialect schema/operation compilation and bound parameters |
| `driftlab/database.py` | Actual engine adapters, isolation, transactions, error categories |
| `driftlab/compare.py` | Outcomes, ordered/bag comparison, findings, advice |
| `driftlab/engine.py` | Comparison execution, evidence, cleanup |
| `driftlab/generate.py` | Seeded edge-case families and controls |
| `driftlab/reduce.py` | Chunk reduction, final deletion proof, repeated witness |
| `driftlab/export.py` | SQL/binding evidence and executable regression bundle |
| `driftlab/jobs.py`, `api.py` | Background queue, history, cancellation, HTTP contract |
| `web/` | Paired-result inspection dashboard |

Read [BUILD_GUIDE.md](BUILD_GUIDE.md) for a learning walkthrough.

## Configuration and storage

Project files, isolated PostgreSQL dependencies, credentials, caches, browser
profile used for QA, reports, exports, and temporary data are on D drive.
`run.ps1` redirects TEMP/TMP and pip cache to this project and disables bytecode.
The existing Python installation and web libraries are read without installing
global packages or modifying them.

Automatic local connection: `.secrets/postgres.json`. To use an independent test
server, set DRIFTLAB_DATABASE_URL instead; it takes precedence. The user needs
CREATE permission in a dedicated test database. Connection strings never enter
reports. This project can run against an external PostgreSQL test database without
CrashLab; the current workstation reuses its existing D-drive server.

On another Windows workstation with Python 3.10+, first set TEMP/TMP and
PIP_CACHE_DIR to D-drive directories, then install using:

```powershell
python -B -m pip install --target D:\db-drift-detective\.vendor --no-compile -r requirements.txt
```

Then supply DRIFTLAB_DATABASE_URL for a dedicated test database. The convenience
setup script can also create a local database/role using administrator credentials
from its environment; on this workstation it used the existing private D-drive
administrator file. No credentials are included in the repository or exports.

## Real-world application: chat import preflight

The [Open WebUI study](case_studies/openwebui_nul/README.md) reproduces a historical,
closed JSON-search failure from a pinned upstream version. All 100 synthetic chats
import successfully, but one NUL-containing message breaks PostgreSQL search.
The tool reduces it to one chat and one search query.

A new non-destructive preflight scans decoded strings, preserves original bytes,
and optionally writes a repaired copy with an audit trail. A literal backslash-u
sequence is not confused with an actual NUL code point.

```powershell
.\run.ps1 chat-preflight case_studies\openwebui_nul\sample-export.json
.\run.ps1 chat-preflight case_studies\openwebui_nul\sample-export.json --repair --verify
python -B scripts\real_world_study.py
```

Repair is an explicit content change: actual decoded NULs become visible [NUL]
markers in a separate file. The dry-run exits 1 when the input violates the policy;
a repaired output that passes the NUL policy exits 0. The optional verification
checks message-body search on both databases, not the entire upstream application.
See REAL_WORLD_VALIDATION.txt for the expanded test suite and
case_studies/openwebui_nul/latest.json for evidence paths.
