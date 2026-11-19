"""Small asynchronous D1 interface; no Cloudflare API credentials in application code."""
import json


def plain(value):
    if hasattr(value, 'to_py'):
        value = value.to_py()
    return value


class D1Store:
    def __init__(self, binding):
        self.binding = binding

    def statement(self, sql, params):
        return self.binding.prepare(sql).bind(*params)

    async def one(self, sql, *params):
        return plain(await self.statement(sql, params).first())

    async def all(self, sql, *params):
        result = plain(await self.statement(sql, params).all())
        return result['results']

    async def execute(self, sql, *params):
        return plain(await self.statement(sql, params).run())

    async def batch(self, queries):
        from pyodide.ffi import to_js
        return plain(await self.binding.batch(to_js([self.statement(sql, params) for sql, params in queries])))
