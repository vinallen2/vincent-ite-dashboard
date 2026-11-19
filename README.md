# Vincent ITE Dashboard

Source-controlled migration of the existing private anesthesiology ITE study dashboard to a Python backend and Cloudflare D1.

## Status

**Migration scaffold only. Not deployed.** The existing ChatGPT-hosted dashboard remains the production application and its database remains authoritative until a verified cutover.

## Intended components

- `frontend/`: existing UI source (to be exported faithfully, not reconstructed from screenshots).
- `backend/`: Python API, grading, session publication and review planning.
- `migrations/`: Cloudflare D1 SQL schema and migrations.
- `tests/`: automated regression tests for immutable first attempts, grading, and daily/bonus semantics.

## Security and migration requirements

1. **Make this GitHub repository private before importing study records or application-specific configuration.** Never commit credentials or private data.
2. Preserve original session IDs, authored questions, first attempts, review records, and article deduplication.
3. November 14, 2026 was a chat-only session explicitly excluded from migration. Do not backfill it.
4. Keep the existing website live during development; do not change automations or switch databases until parity tests and readback pass.
5. Daily sessions and optional bonus sessions share accuracy and topic performance, but only completed daily sessions count toward the daily streak.
6. Use environment bindings for D1 and secrets; never hardcode API tokens.

## Next implementation steps

- Export existing frontend source and current API contract through an authorized mechanism.
- Implement and test Python endpoints against that contract.
- Create D1 database and apply reviewed migrations.
- Import and reconcile existing data, test private authentication, then deploy a staging Worker.
- Update ChatGPT automations and connector only after the new backend has passed verification.
