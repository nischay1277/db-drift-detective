# Real-world study: imported chats work until PostgreSQL search reads them

DB Drift Detective now has a concrete application: detecting and preventing an
imported-chat data defect that can turn an otherwise successful migration into
a broken search feature.

## Where the problem came from

[Open WebUI issue #15616](https://github.com/open-webui/open-webui/issues/15616)
reported this failure in v0.6.15: JSON chat data containing escaped NUL characters
could lead to PostgreSQL search errors. The issue is historical and closed. This
study does not claim to discover a new bug, fix the current upstream release,
or run the complete Open WebUI application.

The [v0.6.15 chat model](https://github.com/open-webui/open-webui/blob/v0.6.15/backend/open_webui/models/chats.py)
declares a JSON chat column and different JSON-array search paths for SQLite and
PostgreSQL. Our fixture follows that message-array extraction pattern. It omits
the surrounding authorization, title OR condition, tags, and pagination, allowing
the database-specific failure to be tested in isolation.

PostgreSQL's [JSON documentation](https://www.postgresql.org/docs/17/datatype-json.html)
explains the relevant distinction: JSON input can preserve escaped Unicode that
subsequent processing cannot turn into PostgreSQL text. JSONB has stricter input
checks. Merely proving that an import succeeds does not prove that later features
can process the imported values.

## What was actually reproduced

The input is a synthetic export-shaped array of 100 chats. One message contains an
actual decoded U+0000 character; its serialized JSON contains an escaped form.
No real user chats or credentials were collected.

| Check | Before repair | After explicit copy repair |
| --- | --- | --- |
| All 100 imports accepted on SQLite | Yes | Yes |
| All 100 imports accepted on PostgreSQL JSON | Yes | Yes |
| SQLite message search | Returns the matching chat | Returns the matching chat |
| PostgreSQL message search | SQLSTATE 22P05 | Returns the matching chat |
| Cross-engine findings | One operation-acceptance difference | None |
| Original input | Preserved | Still preserved |

The reducer isolates the failure to **one poisoned chat and one search operation**.
It verifies that deleting either remaining input stops reproducing the same
finding. The schema remains fixed, and the generated fixture IDs differ from
the application's IDs. This is a database-level reproduction, not an HTTP 500
measurement from a deployed Open WebUI server.

## A practical remedy someone can use

The new `chat-preflight` command inspects decoded JSON before it is imported.

```powershell
cd D:\db-drift-detective

# Inspect only; a failing NUL policy returns exit code 1
.\run.ps1 chat-preflight case_studies\openwebui_nul\sample-export.json

# Create a repaired COPY, preserve the original, and test both database behaviors
.\run.ps1 chat-preflight case_studies\openwebui_nul\sample-export.json --repair --verify
```

It writes an isolated output directory under D:\db-drift-detective\runs:

- `original.json`: the exact original input bytes.
- `repaired.json`: a separate file replacing actual decoded NULs with `[NUL]`.
- `audit.json`: changed JSON-pointer paths, occurrence counts, hashes, policy, and
  before/after verification report paths.
- `before-case.json` and `after-case.json` when verification is enabled.

The repair changes content deliberately and visibly. It does not silently discard
a whole chat or erase the only original copy. Literal six-character `\u0000`
text is preserved. Unicode text and ordinary newlines are preserved. Duplicate
JSON keys and repair-induced key collisions are rejected rather than guessed at.

The accepted shapes are a chat object, an array of chat objects, or an object
with a chats array. Each payload must have a messages array. This validates a
specific NUL policy, not every upstream import requirement. The optional database
verification isolates message-body search, not the full application's behavior.

## Improvements to DB Drift Detective

1. Added JSON columns: checked JSON text in SQLite and native JSON in PostgreSQL.
2. Added a bounded JSON-array text-search predicate with validated paths and bound
   search values, instead of accepting arbitrary SQL from the dashboard.
3. Added semantic JSON normalization for paired results and snapshots.
4. Distinguished PostgreSQL encoding errors from driver/infrastructure failures
   so a malformed placeholder cannot become a false compatibility finding.
5. Added original/repaired case presets to the dashboard and seeded generator.
6. Added dry-run import scanning, explicit copy repair, audit trails, and tests
   for literal escape preservation and key collisions.

## Reproduce the entire study

```powershell
python -B scripts\real_world_study.py
python -B -m unittest discover -s tests -v
```

`latest.json` points to the actual comparison, reduction, audit, and fixed reports,
plus before/after reproduction bundles. `dashboard.json` links to inspectable runs
in the local workbench. `REAL_WORLD_VALIDATION.txt` at the project root records
the full test suite.

The minimal reproduction script exits 0 when the historical behavior is reproduced.
Its compatibility regression intentionally fails before repair and passes on the
repaired case. Those are separate checks; an expected failing compatibility test
is not reported as a passing compatibility result.

## Why this matters for the Amazon Programmer Analyst internship

| Internship requirement | Evidence from this study |
| --- | --- |
| Support platform migrations | Detect data accepted by the new database but unusable by a later feature |
| Troubleshoot application issues | Trace a search failure to one value, one query, and SQLSTATE 22P05 |
| Build/modify internal tools | Add a repeatable preflight, explicit repair workflow, and audit output |
| Write code and tests | Protect Unicode/escape handling and execute regression tests on both engines |
| Translate operational needs | Preserve chat history and restore search without silently discarding records |

An honest resume bullet:

> Extended a SQLite/PostgreSQL differential testing tool to reproduce a historical
> Open WebUI JSON-search regression, reduced 100 imported chats to a one-record
> reproducer, and built an audited import preflight with cross-database regression tests.

This evidence supports migration/debugging/tooling skills. It does not establish
AWS experience, an upstream contribution, production deployment, or user impact
measured in a real organization.
