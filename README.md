# Vincent ITE Dashboard

Python/FastAPI migration of the existing private Anesthesiology ITE study app.

**Cutover is pending.** The original private ChatGPT Site remains production and
authoritative. A separate D1 staging copy was imported and reconciled against
the authorized API readbacks on November 19, 2026. Do not direct new submissions
to both databases. Refresh and verify the snapshot immediately before cutover.

## Source

- `frontend/` contains the actual recovered HTML, CSS and JavaScript, including
  daily and bonus sessions, saved questions, articles and deeper analytics.
- `backend/` contains Python grading, persistence, performance aggregation,
  review planning, article deduplication and the FastAPI endpoints.
- `gateway/` and `scripts/build_frontend.mjs` prepare the existing private Site
  to serve the UI and forward API calls to Python after cutover.
- `migrations/0001_initial.sql` retains the production table/column names,
  original IDs and JSON payloads. It replaces the never-applied draft scaffold
  schema. No production data or API credentials are committed.
- `scripts/prepare_migration.py` reconciles authorized local exports and prepares
  an idempotent import. Exports remain ignored under `.runtime/`.

The source was recovered from the original Sites repository at commit
`92f64c8194a785c2f1e6dc31ab80349dc7f0de77`.

## Preserved behavior

- Exactly three questions per published daily or optional bonus session; legacy
  four-option sets and new three-option sets both work.
- First attempts cannot be replaced. Duplicate/racing submissions return the
  original saved result and do not duplicate review records.
- Daily and bonus questions share accuracy and topic history. Bonus completion
  never adds a daily streak date. Dates use America/New_York.
- Questions, every option explanation, references, chosen answers, confidence,
  timestamps, pending GPT planning state and planning receipts are retained.
- Historical aggregate-only scores remain aggregates; absent stems/answers
  are never reconstructed. Unanswered sets never count as graded questions.
- Reviews and articles preserve IDs. Article matching normalizes DOI and title.
- November 14's chat-only session is explicitly excluded from migration.
- The original Google Sheet remains an untouched historical archive.

## Private authentication

The current owner-private Sites login remains the user-facing gate and URL.
The Python service additionally requires a high-entropy `GATEWAY_TOKEN` on
**every** route. A forged user-id header alone grants no access. API docs are
disabled. POST requests reject cross-site origins. Secrets belong in runtime
secret bindings, never Git, exported JSON, build output or browser code.

No backend route is enabled. Automatic approval review blocked creation of a
public `workers.dev` subdomain. Public routing requires explicit owner approval,
even with the secret protecting application data. Do not retry that action
indirectly. The original Site's audience has not changed.

## Local validation

Use Python 3.13 or later. Install the project and test dependencies in a virtual
environment, then run:

```sh
python -m pytest -q
node scripts/test_gateway.mjs
node scripts/build_frontend.mjs
node --check dist/server/index.js
```

`python scripts/prepare_migration.py` requires fresh authorized
`.runtime/context-export.json` and `.runtime/public-export.json`. It performs
SQLite reconstruction, exact session/attempt/performance/review/article parity
checks and a replay before producing `.runtime/import-batch.json`. Verify the
remote D1 rows as well; counts alone are insufficient.

## Before cutover

1. Complete the Cloudflare Python runtime package/build validation. The Python
   service tests pass on CPython, but the Cloudflare runtime has not yet been
   verified. `cf` is the selected project CLI; do not silently introduce a
   conflicting Wrangler project. The installed `cf` release requests
   `cloudflare-py-dev-server`, which is unavailable in the package registry used
   in this environment. Its Python build therefore remains blocked. No
   Cloudflare runtime deployment has been claimed or performed.
2. Obtain approval for the backend's protected network address. Configure its
   gateway secret before enabling a route, then verify anonymous requests and
   forged user headers are rejected.
3. Refresh the source readbacks, reconcile every row and re-import only missing
   records. Preserve submission IDs and first attempts; detect conflicts.
4. Configure secret `ITE_BACKEND_TOKEN` and `ITE_BACKEND_URL` in the existing
   private Site, deploy the prepared gateway, and verify the same native
   `ite_study` connector and browser API against Python.
5. Test owner authentication, save/readback and failure handling. Do not submit
   synthetic scored answers to production. Keep the original DB intact for
   recovery and avoid split writes.
6. Keep the review-before-questions preference and post-completion companion
   email timing. Do not replace current automation prompts with old versions.

Until these checks pass, existing automations and the live Site continue using
the original database.
