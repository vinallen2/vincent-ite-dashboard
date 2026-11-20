"""No network or production data required for adapter tests."""
import asyncio
import httpx
import pytest
from backend.d1_http import D1HTTPStore, D1HTTPError


def run(coro):
    return asyncio.run(coro)


def test_query_json_and_parameters():
    seen = []
    def handle(request):
        seen.append((request.headers["authorization"], request.url.path, request.content))
        return httpx.Response(200, json={"success": True, "result": [{"success": True, "results": [{"id": "abc"}]}]})
    with httpx.Client() as sync_client:
        pass
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            store = D1HTTPStore("acct", "db", "secret", client=client)
            assert await store.one("SELECT id FROM study_sessions WHERE id=?", "abc") == {"id": "abc"}
    run(scenario())
    assert len(seen) == 1
    assert seen[0][0] == "Bearer secret"
    assert b'"params":["abc"]' in seen[0][2]


def test_api_failure_is_not_silent():
    def handle(request):
        return httpx.Response(200, json={"success": False, "errors": [{"message": "denied"}]})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(D1HTTPError):
                await D1HTTPStore("a", "b", "token", client=client).all("SELECT 1")
    run(scenario())
