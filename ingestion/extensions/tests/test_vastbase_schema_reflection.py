import importlib.util
import unittest
from pathlib import Path


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
# numeric_scale, is_nullable, column_default, ordinal_position, comment
COLUMN_ROWS = [
    ("id", "integer", None, 32, 0, "NO", None, 1, "主键ID"),
    ("name", "character varying", 50, None, None, "YES", None, 2, "名称"),
    ("plain", "character varying", 20, None, None, "YES", None, 3, None),
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
            ["主键ID", "名称", None],
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

        self.assertEqual([1, 2, 3], [column["ordinalPosition"] for column in columns])


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
