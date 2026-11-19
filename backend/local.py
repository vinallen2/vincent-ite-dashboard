"""SQLite adapter for local tests and migration reconciliation only."""
import sqlite3


class SQLiteStore:
    def __init__(self, path=':memory:'):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')

    async def one(self, sql, *params):
        row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    async def all(self, sql, *params):
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    async def execute(self, sql, *params):
        with self.conn:
            self.conn.execute(sql,params)

    async def batch(self, queries):
        with self.conn:
            for sql, params in queries:
                self.conn.execute(sql,params)
