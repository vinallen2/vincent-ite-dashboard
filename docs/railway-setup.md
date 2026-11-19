# Railway staging setup (not production cutover)

This branch adds a standard ASGI entrypoint via `backend.app:app` and a Cloudflare D1 REST adapter.
No credentials belong in GitHub or frontend JavaScript.

Required Railway service variables:
- `GATEWAY_TOKEN`: a new high-entropy secret also installed in the existing owner-private Sites gateway
- `CLOUDFLARE_ACCOUNT_ID`: Cloudflare account ID
- `CLOUDFLARE_D1_DATABASE_ID`: the intended D1 database UUID (staging until cutover)
- `CLOUDFLARE_API_TOKEN`: scoped Cloudflare API token with D1 query access
- `SITE_ORIGIN`: the exact existing private Site origin

The website gateway receives `ITE_BACKEND_URL` and `ITE_BACKEND_TOKEN` only after a private, authenticated end-to-end check. Never expose a Cloudflare token or gateway secret to the browser. Railway-generated domains are publicly reachable even if FastAPI requires a gateway secret; deploying to such a domain requires explicit approval for a public network address.

Before cutover: run local tests; validate D1 readback against the original source; verify 401 without token and forged user headers, 403 on cross-site writes; confirm no answer keys before grading; verify first-attempt immutability and streak behavior; preserve the original database as the only writer until cutover. Do not write synthetic scored answers into production.
