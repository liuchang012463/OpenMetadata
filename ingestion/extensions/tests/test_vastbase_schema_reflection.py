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


class FakeConnection:
    info_cache = {}

    def __init__(self, schemas, current_schema):
        self.schemas = schemas
        self.current_schema = current_schema
        self.statements = []

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if "SELECT CURRENT_SCHEMA" in sql:
            return Result([(self.current_schema,)])
        return Result(self.schemas)


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


if __name__ == "__main__":
    unittest.main()
