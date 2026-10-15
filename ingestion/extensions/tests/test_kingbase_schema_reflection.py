import unittest

from sqlalchemy import types as sqltypes

import kingbase_connector.kingbase_dialect as kingbase_dialect
from kingbase_connector.kingbase_dialect import _col_type


class Result(list):
    def scalar(self):
        return self[0][0] if self else None


class FakeConnection:
    info_cache = {}

    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def execute(self, statement, parameters=None):
        self.statements.append(str(statement))
        return Result(self.rows)


# (column_name, data_type, character_maximum_length, numeric_precision,
#  numeric_scale, is_nullable, column_default, ordinal_position, udt_name,
#  formatted_type, comment)
REPORTED_TABLE_ROWS = [
    (
        "id",
        "USER-DEFINED",
        None,
        None,
        None,
        "NO",
        None,
        1,
        "varcharbyte",
        "character varying(32 byte)",
        None,
    ),
    (
        "dataid",
        "USER-DEFINED",
        None,
        None,
        None,
        "NO",
        None,
        2,
        "varcharbyte",
        "character varying(32 byte)",
        "主键标识",
    ),
    (
        "verdsec_v",
        "USER-DEFINED",
        None,
        None,
        None,
        "YES",
        None,
        3,
        "varcharbyte",
        "character varying(200 byte)",
        "版本描述",
    ),
    (
        "task_status_v",
        "numeric",
        None,
        1,
        0,
        "YES",
        None,
        4,
        "numeric",
        "numeric(1,0)",
        None,
    ),
    (
        "verdate_v",
        "timestamp without time zone",
        None,
        None,
        None,
        "YES",
        None,
        5,
        "timestamp",
        "timestamp(6) without time zone",
        None,
    ),
]


class KingbaseByteStringTypeTest(unittest.TestCase):
    """(n BYTE) declarations are USER-DEFINED in KingbaseES Oracle mode."""

    def test_character_varying_byte_becomes_varchar_with_length(self):
        column_type = _col_type(
            "USER-DEFINED", None, None, None, "varcharbyte", "character varying(32 byte)"
        )

        self.assertIsInstance(column_type, sqltypes.VARCHAR)
        self.assertEqual(32, column_type.length)

    def test_character_varying_byte_without_length_stays_unbounded(self):
        column_type = _col_type(
            "USER-DEFINED", None, None, None, "varcharbyte", "character varying"
        )

        self.assertIsInstance(column_type, sqltypes.VARCHAR)
        self.assertIsNone(column_type.length)

    def test_char_byte_becomes_char_with_length(self):
        column_type = _col_type(
            "USER-DEFINED", None, None, None, "bpcharbyte", "character(8 byte)"
        )

        self.assertIsInstance(column_type, sqltypes.CHAR)
        self.assertEqual(8, column_type.length)

    def test_unknown_user_defined_type_is_not_guessed(self):
        column_type = _col_type(
            "USER-DEFINED", None, None, None, "geometry", "geometry"
        )

        self.assertIsInstance(column_type, sqltypes.NullType)

    def test_unrecognised_user_defined_type_falls_back_to_format_type(self):
        column_type = _col_type(
            "USER-DEFINED", None, None, None, "varcharbyte_new", "character varying(64 byte)"
        )

        self.assertIsInstance(column_type, sqltypes.VARCHAR)
        self.assertEqual(64, column_type.length)


class KingbaseCatalogTypeNameTest(unittest.TestCase):
    """Catalog spellings observed on KingbaseES V009R001C010 (Oracle mode)."""

    def test_bpchar_data_type_maps_to_char(self):
        column_type = _col_type("bpchar", 8, None, None, "bpchar", "character(8 char)")

        self.assertIsInstance(column_type, sqltypes.CHAR)
        self.assertEqual(8, column_type.length)

    def test_varchar_data_type_uses_character_maximum_length(self):
        column_type = _col_type("varchar", 50, None, None, "varchar", "character varying(50 char)")

        self.assertIsInstance(column_type, sqltypes.VARCHAR)
        self.assertEqual(50, column_type.length)

    def test_unbounded_varchar_keeps_no_length(self):
        column_type = _col_type("varchar", None, None, None, "varchar", "varchar")

        self.assertIsInstance(column_type, sqltypes.VARCHAR)
        self.assertIsNone(column_type.length)

    def test_time_without_time_zone_maps_to_time(self):
        column_type = _col_type(
            "time without time zone", None, None, None, "time", "time without time zone"
        )

        self.assertIsInstance(column_type, sqltypes.TIME)

    def test_padded_data_type_is_tolerated(self):
        column_type = _col_type(" VARCHAR  ", 10, None, None, "varchar", "character varying(10 char)")

        self.assertIsInstance(column_type, sqltypes.VARCHAR)
        self.assertEqual(10, column_type.length)

    def test_numeric_keeps_precision_and_scale(self):
        column_type = _col_type("numeric", None, 10, 2, "numeric", "numeric(10,2)")

        self.assertIsInstance(column_type, sqltypes.NUMERIC)
        self.assertEqual(10, column_type.precision)
        self.assertEqual(2, column_type.scale)


class KingbaseColumnReflectionTest(unittest.TestCase):
    def test_get_columns_returns_column_comments(self):
        connection = FakeConnection(REPORTED_TABLE_ROWS)

        columns = kingbase_dialect.KingbaseDialect().get_columns(
            connection, "T_ZTSJ_JX_JZ_YK", "public"
        )

        self.assertEqual(
            ["id", "dataid", "verdsec_v", "task_status_v", "verdate_v"],
            [column["name"] for column in columns],
        )
        self.assertEqual(
            [None, "主键标识", "版本描述", None, None],
            [column["comment"] for column in columns],
        )

    def test_get_columns_maps_byte_string_columns_to_real_types(self):
        connection = FakeConnection(REPORTED_TABLE_ROWS)

        columns = kingbase_dialect.KingbaseDialect().get_columns(
            connection, "T_ZTSJ_JX_JZ_YK", "public"
        )

        by_name = {column["name"]: column["type"] for column in columns}
        self.assertIsInstance(by_name["id"], sqltypes.VARCHAR)
        self.assertEqual(32, by_name["id"].length)
        self.assertIsInstance(by_name["verdsec_v"], sqltypes.VARCHAR)
        self.assertEqual(200, by_name["verdsec_v"].length)
        self.assertIsInstance(by_name["task_status_v"], sqltypes.NUMERIC)

    def test_get_columns_joins_column_comments_and_format_type(self):
        connection = FakeConnection(REPORTED_TABLE_ROWS)

        kingbase_dialect.KingbaseDialect().get_columns(
            connection, "T_ZTSJ_JX_JZ_YK", "public"
        )

        statement = connection.statements[0]
        self.assertIn("pg_catalog.pg_description", statement)
        self.assertIn("format_type", statement)
        self.assertIn("c.udt_name", statement)


if __name__ == "__main__":
    unittest.main()
