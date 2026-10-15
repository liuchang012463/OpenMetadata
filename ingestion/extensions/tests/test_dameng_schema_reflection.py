import unittest

from sqlalchemy import types as sqltypes

import dameng_connector.dm_dialect as dm_dialect
from dameng_connector.dm_dialect import _col_type


class Result(list):
    def scalar(self):
        return self[0][0] if self else None

    def fetchone(self):
        return self[0] if self else None


class FakeConnection:
    """Dispatches on SQL text so one connection can serve several queries."""

    info_cache = {}

    def __init__(self, column_rows=(), other_rows=()):
        self.column_rows = column_rows
        self.other_rows = other_rows
        self.statements = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append(sql)
        if "ALL_TAB_COLUMNS" in sql:
            return Result(self.column_rows)
        return Result(self.other_rows)


# COLUMN_NAME, DATA_TYPE, DATA_LENGTH, DATA_PRECISION, DATA_SCALE, NULLABLE,
# COLUMN_ID, DATA_DEFAULT, COMMENTS, CHAR_LENGTH
COLUMN_ROWS = [
    ("C_VARCHAR", "VARCHAR", 50, None, 0, "Y", 1, None, "VARCOMMENT", 50),
    ("C_CHAR", "CHAR", 8, None, 0, "Y", 2, None, "CHARCOMMENT", 8),
    ("C_INT", "INT", 4, None, 0, "Y", 3, None, None, 0),
    ("C_NCHAR", "NCHAR", 40, None, 0, "Y", 4, None, None, 10),
    ("C_BINARY", "BINARY", 16, None, 0, "Y", 5, None, None, 0),
]


class DamengColumnCommentTest(unittest.TestCase):
    def test_get_columns_returns_column_comments(self):
        connection = FakeConnection(column_rows=COLUMN_ROWS)

        columns = dm_dialect.DamengDialect().get_columns(
            connection, "ZZ_OM_PROBE", "SYSDBA"
        )

        self.assertEqual(
            ["VARCOMMENT", "CHARCOMMENT", None, None, None],
            [column["comment"] for column in columns],
        )

    def test_get_columns_joins_all_col_comments(self):
        connection = FakeConnection(column_rows=COLUMN_ROWS)

        dm_dialect.DamengDialect().get_columns(connection, "ZZ_OM_PROBE", "SYSDBA")

        statement = connection.statements[0]
        self.assertIn("ALL_COL_COMMENTS", statement)
        self.assertIn("cc.COMMENTS", statement)

    def test_get_columns_keeps_ordinal_position(self):
        connection = FakeConnection(column_rows=COLUMN_ROWS)

        columns = dm_dialect.DamengDialect().get_columns(
            connection, "ZZ_OM_PROBE", "SYSDBA"
        )

        self.assertEqual(
            [1, 2, 3, 4, 5],
            [column["ordinalPosition"] for column in columns],
        )

    def test_get_columns_without_schema_does_not_filter_owner(self):
        connection = FakeConnection(column_rows=COLUMN_ROWS)

        dm_dialect.DamengDialect().get_columns(connection, "ZZ_OM_PROBE")

        self.assertNotIn("c.OWNER = :schema", connection.statements[0])


if __name__ == "__main__":
    unittest.main()
