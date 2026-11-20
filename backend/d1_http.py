"""Cloudflare D1 REST adapter for an external ASGI host such as Railway.

Credentials are server-side only. D1's JSON envelope must report success.
"""
import httpx


class D1HTTPError(RuntimeError):
    pass


class D1HTTPStore:
    def __init__(self, account_id, database_id, api_token, client=None):
        if not all((account_id, database_id, api_token)):
            raise ValueError("Cloudflare D1 credentials are not configured")
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query"
        self.token = api_token
        self.client = client

    async def _query(self, sql, params):
        headers = {"Authorization": f"Bearer {self.token}"}
        payload = {"sql": sql, "params": list(params)}
        if self.client is None:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(self.url, headers=headers, json=payload)
        else:
            response = await self.client.post(self.url, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        if not body.get("success") or not isinstance(body.get("result"), list) or not body["result"]:
            raise D1HTTPError("Cloudflare D1 query failed")
        result = body["result"][0]
        if not result.get("success", True):
            raise D1HTTPError("Cloudflare D1 statement failed")
        return result.get("results") or []

    async def one(self, sql, *params):
        rows = await self._query(sql, params)
        return rows[0] if rows else None

    async def all(self, sql, *params):
        return await self._query(sql, params)

    async def execute(self, sql, *params):
        await self._query(sql, params)

    async def batch(self, queries):
        # Idempotent review updates; deliberately sequential rather than pretending
        # independent HTTP requests constitute a database transaction.
        for sql, params in queries:
            await self.execute(sql, *params)
