from __future__ import annotations

import time

from stats_core.storage import sqlite


class ProductRepository:
    def list(self):
        with sqlite.connect() as con:
            rows = con.execute(
                "SELECT product, close_rate, updated_at FROM product_close "
                "ORDER BY close_rate DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def replace(self, rows):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with sqlite.connect() as con:
            con.execute("DELETE FROM product_close")
            for row in rows:
                product = str(row.get("product") or "").strip()
                if not product:
                    continue
                con.execute(
                    "INSERT OR REPLACE INTO product_close "
                    "(product, close_rate, updated_at) VALUES (?,?,?)",
                    (product, float(row.get("close_rate") or 0), stamp),
                )
