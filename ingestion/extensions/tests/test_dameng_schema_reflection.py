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


class DamengColumnTypeTest(unittest.TestCase):
    def test_string_types_keep_the_declared_character_length(self):
        self.assertEqual(50, _col_type("VARCHAR", None, 0, 50, 50).length)
        self.assertEqual(8, _col_type("CHAR", None, 0, 8, 8).length)
        self.assertEqual(120, _col_type("VARCHAR2", None, 0, 120, 120).length)

    def test_nchar_uses_char_length_not_the_byte_width(self):
        # Dameng reports DATA_LENGTH=40 (bytes) for NCHAR(10).
        column_type = _col_type("NCHAR", None, 0, char_length=10, data_length=40)

        self.assertEqual(10, column_type.length)

    def test_nvarchar2_uses_char_length_not_the_byte_width(self):
        column_type = _col_type("NVARCHAR2", None, 0, char_length=30, data_length=120)

        self.assertEqual(30, column_type.length)

    def test_binary_uses_data_length(self):
        self.assertEqual(16, _col_type("BINARY", None, 0, 0, 16).length)
        self.assertEqual(32, _col_type("VARBINARY", None, 0, 0, 32).length)

    def test_binary_maps_to_binary_not_varbinary(self):
        self.assertIsInstance(_col_type("BINARY", None, 0, 0, 16), sqltypes.BINARY)
        self.assertIsInstance(_col_type("VARBINARY", None, 0, 0, 32), sqltypes.VARBINARY)

    def test_numeric_types_do_not_take_the_storage_width(self):
        for name in ("INT", "NUMBER", "DECIMAL", "BIGINT"):
            with self.subTest(name=name):
                column_type = _col_type(name, 18, 4, char_length=0, data_length=22)

                self.assertFalse(getattr(column_type, "length", None))

    def test_numeric_keeps_precision_and_scale(self):
        column_type = _col_type("NUMBER", 18, 4, char_length=0, data_length=22)

        self.assertIsInstance(column_type, sqltypes.NUMERIC)
        self.assertEqual(18, column_type.precision)
        self.assertEqual(4, column_type.scale)

    def test_rowid_and_byte_are_no_longer_null_type(self):
        self.assertIsInstance(_col_type("ROWID", None, 0), sqltypes.VARCHAR)
        self.assertIsInstance(_col_type("UROWID", None, 0), sqltypes.VARCHAR)
        self.assertIsInstance(_col_type("BYTE", None, 0), sqltypes.SMALLINT)

    def test_display_type_carries_the_declared_size(self):
        self.assertEqual(
            "VARCHAR(50)",
            dm_dialect._display_type("VARCHAR", None, 0, 50, 50),
        )
        self.assertEqual(
            "NCHAR(10)",
            dm_dialect._display_type("NCHAR", None, 0, 10, 40),
        )
        self.assertEqual(
            "NUMBER(18,4)",
            dm_dialect._display_type("NUMBER", 18, 4, 0, 22),
        )
        self.assertEqual(
            "BINARY(16)",
            dm_dialect._display_type("BINARY", None, 0, 0, 16),
        )

    def test_display_type_leaves_unsized_types_bare(self):
        self.assertEqual("INT", dm_dialect._display_type("INT", None, 0, 0, 4))
        self.assertEqual("CLOB", dm_dialect._display_type("CLOB", None, 0, 0, 2147483647))

    def test_unknown_type_still_falls_back_to_null_type(self):
        self.assertIsInstance(_col_type("AQ$_SUBSCRIBERS", None, 0), sqltypes.NullType)


class DamengConstraintReflectionTest(unittest.TestCase):
    def test_foreign_keys_are_grouped_per_constraint(self):
        connection = FakeConnection(
            other_rows=[
                ("FK_CHILD_PARENT", "PARENT_ID", "SYSDBA", "ZZ_OM_PARENT", "ID"),
                ("FK_CHILD_OTHER", "OTHER_ID", "SYSDBA", "ZZ_OM_OTHER", "ID"),
            ]
        )

        foreign_keys = dm_dialect.DamengDialect().get_foreign_keys(
            connection, "ZZ_OM_CHILD", "SYSDBA"
        )

        self.assertEqual(
            [
                {
                    "name": "FK_CHILD_PARENT",
                    "constrained_columns": ["PARENT_ID"],
                    "referred_schema": "SYSDBA",
                    "referred_table": "ZZ_OM_PARENT",
                    "referred_columns": ["ID"],
                },
                {
                    "name": "FK_CHILD_OTHER",
                    "constrained_columns": ["OTHER_ID"],
                    "referred_schema": "SYSDBA",
                    "referred_table": "ZZ_OM_OTHER",
                    "referred_columns": ["ID"],
                },
            ],
            foreign_keys,
        )

    def test_composite_foreign_key_keeps_column_order(self):
        connection = FakeConnection(
            other_rows=[
                ("FK_COMPOSITE", "A", "SYSDBA", "ZZ_OM_PARENT", "A"),
                ("FK_COMPOSITE", "B", "SYSDBA", "ZZ_OM_PARENT", "B"),
            ]
        )

        foreign_keys = dm_dialect.DamengDialect().get_foreign_keys(
            connection, "ZZ_OM_CHILD", "SYSDBA"
        )

        self.assertEqual(1, len(foreign_keys))
        self.assertEqual(["A", "B"], foreign_keys[0]["constrained_columns"])
        self.assertEqual(["A", "B"], foreign_keys[0]["referred_columns"])

    def test_unique_constraints_are_grouped_per_constraint(self):
        connection = FakeConnection(
            other_rows=[("UQ_CODE", "CODE"), ("UQ_CODE", "TENANT")]
        )

        unique = dm_dialect.DamengDialect().get_unique_constraints(
            connection, "ZZ_OM_PARENT", "SYSDBA"
        )

        self.assertEqual(
            [{"name": "UQ_CODE", "column_names": ["CODE", "TENANT"]}],
            unique,
        )

    def test_indexes_are_reported_one_entry_per_index(self):
        connection = FakeConnection(
            other_rows=[
                ("INDEX1", "UNIQUE", "ID"),
                ("INDEX2", "NONUNIQUE", "PARENT_ID"),
                ("IX_TAG", "NONUNIQUE", "TAG"),
            ]
        )

        indexes = dm_dialect.DamengDialect().get_indexes(
            connection, "ZZ_OM_CHILD", "SYSDBA"
        )

        self.assertEqual(
            [
                {"name": "INDEX1", "unique": True, "column_names": ["ID"]},
                {"name": "INDEX2", "unique": False, "column_names": ["PARENT_ID"]},
                {"name": "IX_TAG", "unique": False, "column_names": ["TAG"]},
            ],
            indexes,
        )

    def test_primary_key_reports_its_constraint_name(self):
        connection = FakeConnection(other_rows=[("PK_ZZ_OM_CHILD", "ID")])

        pk = dm_dialect.DamengDialect().get_pk_constraint(
            connection, "ZZ_OM_CHILD", "SYSDBA"
        )

        self.assertEqual(
            {"constrained_columns": ["ID"], "name": "PK_ZZ_OM_CHILD"}, pk
        )

    def test_primary_key_without_constraint_reports_none(self):
        connection = FakeConnection(other_rows=[])

        pk = dm_dialect.DamengDialect().get_pk_constraint(
            connection, "ZZ_OM_CHILD", "SYSDBA"
        )

        self.assertEqual({"constrained_columns": [], "name": None}, pk)


if __name__ == "__main__":
    unittest.main()
