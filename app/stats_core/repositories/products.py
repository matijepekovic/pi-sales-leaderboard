from __future__ import annotations

from stats_core.storage import sqlite as database


class ProductRepository:
    def list(self):
        return database.get_product_close()

    def replace(self, rows):
        return database.replace_product_close(rows)
