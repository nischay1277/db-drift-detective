# Understand DB Drift Detective in implementation order

## 1. Start from a concrete mismatch

Run the null-ordering case and its fixed control. Open their reports and compare
the actual returned IDs. Read cases/null_order.json and model.py to understand
how a logical operation is represented without accepting arbitrary SQL.

Exercise: remove the explicit nulls policy from the fixed case and confirm drift
returns. Keep the primary-key tie breaker so the experiment is deterministic.

## 2. Follow the two database adapters

Read sql.py, then database.py. The logical schema becomes dialect SQL with bound
values. Every write/read operation gets its own transaction. A rejected insert
rolls back that operation, allowing subsequent operations to run on both engines.

Exercise: insert a duplicate primary key, then perform an update and select.
Both engines should reject the duplicate and still process the remaining steps.
Compare normalized error categories rather than treating different error wording
as an application-behavior difference.

Each run uses a fresh SQLite file and a generated PostgreSQL schema, then removes
that schema after snapshots are collected. Database setup is separate from the
comparison engine, and application credentials are non-superuser credentials.

## 3. Understand what is compared

Read compare.py. Differences include accepted/rejected writes, rejection categories,
affected row counts, selected rows, and final table contents.

Ordered comparisons require a total order through the primary key. Bag comparison
ignores row ordering but preserves duplicate multiplicity. Numeric whole-valued
floats and integers normalize together; text stays text.

Exercise: reverse a result's physical row order without changing the bag. It
should not be flagged. Replace one duplicate with a different row: it should be.

## 4. Generate repeatable larger cases

Read generate.py. Each family has a concrete witness plus seed-controlled noise.
The tool records whether SQLite strict typing or foreign-key enforcement is enabled.
It does not pretend these settings are properties of every SQLite installation.

Exercise: generate 100 or 500 null-ordering rows with the same seed twice. The JSON
must be identical. Change the seed: noise priorities should change, while the
targeted difference should remain reproducible.

## 5. Reduce the witness

Read reduce.py. The reducer preserves the first finding's stable signature.
It first removes chunks of seed rows and operations, then rechecks single deletions
across both dimensions until none reproduce the same signature. The schema is fixed.
Two final re-executions test the retained witness again.

Exercise: reduce the 500-row null-ordering case. Inspect the two retained rows,
one retained query, and the proof entries for deleting each. An invalid trial is
inconclusive, never proof that an input was unnecessary.

Deletion-minimal is not globally smallest. Signature preservation also does not
replace human assessment of the underlying cause.

## 6. Export something another developer can run

Read export.py and a downloaded bundle. SQL templates and bindings preserve inputs
without interpolating potentially hostile strings or embedded NUL characters.

Run reproduce.py: it should verify the saved behavior. Run test_regression.py: a
known drift case should fail its compatibility assertion. Change the case to the
explicit-policy version and rerun: it should pass.

Export files contain the test data but exclude the private connection settings.

## 7. Inspect it through the dashboard

Start run.ps1 serve and open http://127.0.0.1:8766. Generate a case, compare, inspect
both engine outcomes and durable snapshots, replay, reduce, and download the ZIP.
Job links contain an ID, never a filesystem path or executable command.

Read jobs.py and api.py for bounded execution, persistence, cancellation, and
restart behavior. TestClient tests exercise the API with actual database runs;
scripts/demo_dashboard.py also checks the running server over real HTTP.

## Verification and scope

VALIDATION.txt contains the test run. DEMO_RESULTS.json records the dashboard
demonstrations. Tests cover all five difference families, compatible controls,
CRUD, continuing after rejected writes, parameter binding, schema cleanup,
ordered/bag comparison, dataset reduction, reproduction/regression scripts,
API replay, export, cancellation, and history across restart.

No cloud services or mocked PostgreSQL outcomes are used in these comparisons.
Engine behavior is real; generation is intentionally limited to supported cases.
The interface is a prototype for a defined DSL, not a universal SQL migration tool.

## Resume description after reviewing the implementation

Built a SQLite/PostgreSQL differential testing tool that compared query results,
write acceptance, and durable state; reduced a 500-row migration regression to
two rows and one query and exported executable reproductions and regression tests.

Use the recorded local results when discussing performance or scale. Do not claim
production deployment, arbitrary SQL coverage, or general automatic root-cause analysis.

## Primary references

- https://sqlite.org/quirks.html
- https://sqlite.org/lang_expr.html
- https://sqlite.org/pragma.html
- https://www.postgresql.org/docs/17/queries-order.html
- https://www.psycopg.org/psycopg3/docs/basic/transactions.html

## 8. Apply it to a sourced application failure

Read case_studies/openwebui_nul/README.md. The pinned Open WebUI model stores JSON,
which PostgreSQL can accept even when later extraction of message text fails.
The plain-TEXT NUL fixture did not model this delayed failure, so the investigation
added JSON columns and a bounded array-text-search predicate.

Follow chat_import.py: parse, inspect decoded strings, preserve original input,
write an explicitly repaired copy, and verify before/after message search. The
policy leaves literal escape sequences untouched and rejects ambiguous key collisions.

Exercise: run the study, inspect the one-chat reproducer, then run the exported
compatibility tests before and after repair. Distinguish a genuine SQLSTATE 22P05
from a client driver placeholder failure. The latter is an experiment error,
not evidence that databases disagree.

The case is historical and closed upstream. This project supplies a database-level
reproduction and a reusable preflight remedy; it does not claim a new discovery,
an upstream patch, or validation of every Open WebUI workflow.
