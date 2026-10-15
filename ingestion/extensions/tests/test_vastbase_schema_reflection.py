import importlib.util
import unittest
from pathlib import Path

from sqlalchemy import types as sqltypes


DIALECT_PATH = (
    Path(__file__).parent.parent
    / "python/metadata/ingestion/source/database/customdatabase/vastbase_connector/vastbase_dialect.py"
)
SPEC = importlib.util.spec_from_file_location("vastbase_dialect_under_test", DIALECT_PATH)
DIALECT_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIALECT_MODULE)


class Result(list):
    def scalar(self):
        return self[0][0] if self else None

    def fetchone(self):
        return self[0] if self else None


class FakeConnection:
    """Dispatches on SQL text so one connection can serve several queries."""

    info_cache = {}

    def __init__(self, schemas=(), current_schema="public", column_rows=(), comment_rows=()):
        self.schemas = schemas
        self.current_schema = current_schema
        self.column_rows = column_rows
        self.comment_rows = comment_rows
        self.statements = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append(sql)
        if "SELECT CURRENT_SCHEMA" in sql:
            return Result([(self.current_schema,)])
        if "information_schema.columns" in sql:
            return Result(self.column_rows)
        if "pg_catalog.pg_description" in sql:
            return Result(self.comment_rows)
        return Result(self.schemas)


# column_name, data_type, character_maximum_length, numeric_precision,
# numeric_scale, is_nullable, column_default, ordinal_position, udt_name,
# comment
COLUMN_ROWS = [
    ("id", "integer", None, 32, 0, "NO", None, 1, "int4", "主键ID"),
    ("name", "character varying", 50, None, None, "YES", None, 2, "varchar", "名称"),
    ("plain", "character varying", 20, None, None, "YES", None, 3, "varchar", None),
    ("login", "name", None, None, None, "YES", None, 4, "name", None),
    ("useroid", "oid", None, None, None, "YES", None, 5, "oid", None),
    ("payload", "jsonb", None, None, None, "YES", None, 6, "jsonb", None),
    ("tags", "ARRAY", None, None, None, "YES", None, 7, "_int4", None),
    ("at", "time without time zone", None, None, None, "YES", None, 8, "time", None),
]


class VastbaseSchemaReflectionTest(unittest.TestCase):
    def test_returns_all_visible_non_system_schemas(self):
        connection = FakeConnection(
            [
                ("db4ai",),
                ("information_schema",),
                ("myschema",),
                ("pg_catalog",),
                ("public",),
                ("stweb_probe_20261011_a",),
            ],
            current_schema="public",
        )

        schemas = DIALECT_MODULE.VastbaseDialect().get_schema_names(connection)

        self.assertEqual(
            ["myschema", "public", "stweb_probe_20261011_a"],
            schemas,
        )
        self.assertEqual(1, len(connection.statements))


class VastbaseColumnCommentTest(unittest.TestCase):
    def test_get_columns_returns_column_comments(self):
        connection = FakeConnection(column_rows=COLUMN_ROWS)

        columns = DIALECT_MODULE.VastbaseDialect().get_columns(
            connection, "t_demo", "public"
        )

        self.assertEqual(
            ["主键ID", "名称", None, None, None, None, None, None],
            [column["comment"] for column in columns],
        )

    def test_get_columns_reads_comments_from_the_catalog(self):
        connection = FakeConnection(column_rows=COLUMN_ROWS)

        DIALECT_MODULE.VastbaseDialect().get_columns(connection, "t_demo", "public")

        statement = connection.statements[0]
        self.assertIn("pg_catalog.pg_description", statement)
        self.assertIn("pgd.objsubid = a.attnum", statement)

    def test_get_columns_keeps_ordinal_position(self):
        connection = FakeConnection(column_rows=COLUMN_ROWS)

        columns = DIALECT_MODULE.VastbaseDialect().get_columns(
            connection, "t_demo", "public"
        )

        self.assertEqual(
            [1, 2, 3, 4, 5, 6, 7, 8],
            [column["ordinalPosition"] for column in columns],
        )


class VastbaseColumnTypeTest(unittest.TestCase):
    """PostgreSQL spellings the catalog emits and the old mapper dropped."""

    def test_name_is_a_string_not_null_type(self):
        column_type = DIALECT_MODULE._column_type("name", None, None, None, "name")

        self.assertIsInstance(column_type, sqltypes.String)

    def test_oid_is_an_integer_not_null_type(self):
        column_type = DIALECT_MODULE._column_type("oid", None, None, None, "oid")

        self.assertIsInstance(column_type, sqltypes.BIGINT)

    def test_jsonb_maps_to_json(self):
        column_type = DIALECT_MODULE._column_type("jsonb", None, None, None, "jsonb")

        self.assertIsInstance(column_type, sqltypes.JSON)

    def test_time_without_time_zone_maps_to_time(self):
        column_type = DIALECT_MODULE._column_type(
            "time without time zone", None, None, None, "time"
        )

        self.assertIsInstance(column_type, sqltypes.TIME)

    def test_interval_and_money_are_not_null_type(self):
        for name in ("interval", "money", "inet", "cidr", "tsvector"):
            with self.subTest(name=name):
                column_type = DIALECT_MODULE._column_type(name, None, None, None, name)

                self.assertNotIsInstance(column_type, sqltypes.NullType)

    def test_geometric_types_keep_their_postgresql_name(self):
        column_type = DIALECT_MODULE._column_type("point", None, None, None, "point")

        self.assertEqual("POINT", str(column_type))

    def test_array_uses_the_element_type_from_udt_name(self):
        column_type = DIALECT_MODULE._column_type("ARRAY", None, None, None, "_int4")

        self.assertIsInstance(column_type, sqltypes.ARRAY)
        self.assertIsInstance(column_type.item_type, sqltypes.INTEGER)

    def test_unknown_array_element_stays_null_type(self):
        column_type = DIALECT_MODULE._column_type(
            "ARRAY", None, None, None, "_no_such_type"
        )

        self.assertIsInstance(column_type, sqltypes.NullType)

    def test_known_types_are_unchanged(self):
        self.assertIsInstance(
            DIALECT_MODULE._column_type("integer", None, 32, 0, "int4"),
            sqltypes.INTEGER,
        )
        self.assertIsInstance(
            DIALECT_MODULE._column_type("boolean", None, None, None, "bool"),
            sqltypes.BOOLEAN,
        )
        numeric = DIALECT_MODULE._column_type("numeric", None, 10, 2, "numeric")
        self.assertIsInstance(numeric, sqltypes.NUMERIC)
        self.assertEqual(10, numeric.precision)
        self.assertEqual(2, numeric.scale)


class VastbaseTableCommentTest(unittest.TestCase):
    def test_table_comment_only_accepts_the_table_level_row(self):
        connection = FakeConnection(comment_rows=[("tbl comment",)])

        comment = DIALECT_MODULE.VastbaseDialect().get_table_comment(
            connection, "t_demo", "public"
        )

        self.assertEqual({"text": "tbl comment"}, comment)
        self.assertIn("pgd.objsubid = 0", connection.statements[0])

    def test_table_without_a_comment_reports_none(self):
        connection = FakeConnection(comment_rows=[])

        comment = DIALECT_MODULE.VastbaseDialect().get_table_comment(
            connection, "t_demo", "public"
        )

        self.assertEqual({"text": None}, comment)


if __name__ == "__main__":
    unittest.main()
