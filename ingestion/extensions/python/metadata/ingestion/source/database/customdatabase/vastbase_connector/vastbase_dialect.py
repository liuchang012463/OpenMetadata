# Copyright 2026 Collate
# Licensed under the Collate Community License, Version 1.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# https://github.com/open-metadata/OpenMetadata/blob/2.0.4-release/ingestion/LICENSE
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Small SQLAlchemy dialect used by the 2.0.4 CommonDbSourceService."""

from sqlalchemy import sql
from sqlalchemy.dialects import registry
from sqlalchemy.engine import reflection
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.sql import sqltypes

EXCLUDED_SCHEMAS = frozenset(
    {
        "pg_catalog",
        "information_schema",
        "pg_toast",
        "pg_temp_1",
        "pg_toast_temp_1",
        "pg_bitmapindex",
        "db4ai",
        "dbe_perf",
        "dbe_pldeveloper",
        "dbms_pipe",
        "dbms_xplan",
        "sys",
    }
)


def _column_type(data_type, raw_length, precision, scale):
    data_type = str(data_type).upper()
    length = int(raw_length) if raw_length is not None else None
    if data_type in ("INTEGER", "INT", "SERIAL"):
        return sqltypes.INTEGER()
    if data_type in ("BIGINT", "BIGSERIAL"):
        return sqltypes.BIGINT()
    if data_type in ("SMALLINT", "SMALLSERIAL"):
        return sqltypes.SMALLINT()
    if data_type in ("VARCHAR", "CHARACTER VARYING"):
        return sqltypes.VARCHAR(length=length)
    if data_type in ("CHAR", "CHARACTER"):
        return sqltypes.CHAR(length=length)
    if data_type in ("FLOAT", "DOUBLE", "DOUBLE PRECISION"):
        return sqltypes.FLOAT()
    if data_type == "REAL":
        return sqltypes.REAL()
    if data_type in ("DECIMAL", "NUMERIC", "NUMBER"):
        return sqltypes.NUMERIC(precision=precision, scale=scale)
    if data_type == "DATE":
        return sqltypes.DATE()
    if data_type in ("TIMESTAMP", "TIMESTAMP WITHOUT TIME ZONE", "DATETIME"):
        return sqltypes.DATETIME()
    if data_type in ("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ"):
        return sqltypes.TIMESTAMP()
    if data_type == "TIME":
        return sqltypes.TIME()
    if data_type in ("BOOLEAN", "BOOL", "BIT"):
        return sqltypes.BOOLEAN()
    if data_type in ("BYTEA", "BLOB"):
        return sqltypes.BLOB()
    if data_type in ("TEXT", "CLOB"):
        return sqltypes.TEXT()
    if data_type == "JSON":
        return sqltypes.JSON()
    if data_type == "UUID":
        return sqltypes.Uuid()
    return sqltypes.NullType()


@reflection.cache
def get_schema_names(self, connection, **kw):
    rows = connection.execute(
        sql.text(
            "SELECT schema_name FROM ("
            "SELECT schema_name FROM information_schema.schemata "
            "UNION SELECT DISTINCT table_schema AS schema_name "
            "FROM information_schema.tables"
            ") schemas ORDER BY schema_name"
        )
    )
    schemas = [row[0] for row in rows if row[0] not in EXCLUDED_SCHEMAS]
    return schemas


@reflection.cache
def get_table_names(self, connection, schema=None, **kw):
    rows = connection.execute(
        sql.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
        ),
        {"schema": schema or "public"},
    )
    return [row[0] for row in rows]


@reflection.cache
def get_view_names(self, connection, schema=None, **kw):
    rows = connection.execute(
        sql.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_type = 'VIEW'"
        ),
        {"schema": schema or "public"},
    )
    return [row[0] for row in rows]


@reflection.cache
def get_columns(self, connection, table_name, schema=None, **kw):
    rows = connection.execute(
        sql.text(
            "SELECT c.column_name, c.data_type, c.character_maximum_length, "
            "c.numeric_precision, c.numeric_scale, c.is_nullable, "
            "c.column_default, c.ordinal_position, "
            "pgd.description AS comment "
            "FROM information_schema.columns c "
            "LEFT JOIN pg_catalog.pg_namespace pn ON pn.nspname = c.table_schema "
            "LEFT JOIN pg_catalog.pg_class pc "
            "ON pc.relnamespace = pn.oid AND pc.relname = c.table_name "
            "LEFT JOIN pg_catalog.pg_attribute a "
            "ON a.attrelid = pc.oid AND a.attname = c.column_name "
            "AND NOT a.attisdropped "
            "LEFT JOIN pg_catalog.pg_description pgd "
            "ON pgd.objoid = pc.oid AND pgd.objsubid = a.attnum "
            "WHERE c.table_name = :table AND c.table_schema = :schema "
            "ORDER BY c.ordinal_position"
        ),
        {"table": table_name, "schema": schema or "public"},
    )
    columns = []
    for row in rows:
        columns.append(
            {
                "name": row[0],
                "type": _column_type(row[1], row[2], row[3], row[4]),
                "nullable": row[5] == "YES",
                "default": row[6],
                "autoincrement": False,
                "comment": row[8],
                "ordinalPosition": row[7],
            }
        )
    return columns


@reflection.cache
def get_pk_constraint(self, connection, table_name, schema=None, **kw):
    rows = connection.execute(
        sql.text(
            "SELECT kcu.column_name FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "ON tc.constraint_name = kcu.constraint_name "
            "AND tc.table_schema = kcu.table_schema "
            "WHERE tc.table_name = :table AND tc.table_schema = :schema "
            "AND tc.constraint_type = 'PRIMARY KEY' ORDER BY kcu.ordinal_position"
        ),
        {"table": table_name, "schema": schema or "public"},
    )
    return {"constrained_columns": [row[0] for row in rows], "name": None}


@reflection.cache
def get_view_definition(self, connection, view_name, schema=None, **kw):
    row = connection.execute(
        sql.text(
            "SELECT view_definition FROM information_schema.views "
            "WHERE table_name = :view AND table_schema = :schema"
        ),
        {"view": view_name, "schema": schema or "public"},
    ).fetchone()
    return row[0] if row else None


def _empty_constraints(self, connection, table_name, schema=None, **kw):
    return []


@reflection.cache
def get_table_comment(self, connection, table_name, schema=None, **kw):
    row = connection.execute(
        sql.text(
            "SELECT pgd.description FROM pg_catalog.pg_description pgd "
            "JOIN pg_catalog.pg_class pc ON pgd.objoid = pc.oid "
            "JOIN pg_catalog.pg_namespace pn ON pc.relnamespace = pn.oid "
            "WHERE pc.relname = :table AND pn.nspname = :schema "
            "AND pgd.objsubid = 0 LIMIT 1"
        ),
        {"table": table_name, "schema": schema or "public"},
    ).fetchone()
    return {"text": row[0] if row else None}


class VastbaseDialect(DefaultDialect):
    # Vastbase speaks the PostgreSQL SQL dialect.  Keep the URL key as
    # ``vastbase`` below, but expose the SQLAlchemy dialect name as
    # ``postgresql`` so OpenMetadata 2.0.4 reuses its PostgreSQL profiler
    # compilers (notably LENGTH instead of the default MSSQL-style LEN).
    name = "postgresql"
    supports_statement_cache = True
    supports_alter = True
    supports_pk_autoincrement = True
    supports_schemas = True
    supports_sequences = True
    supports_native_boolean = True
    supports_native_decimal = True
    supports_native_enum = False
    supports_native_uuid = True
    returns_native_bytes = False
    description_encoding = None
    server_version_info = None
    default_schema_name = "public"
    supports_comments = True

    def initialize(self, connection):
        self.server_version_info = None

    def has_table(self, connection, table_name, schema=None, **kw):
        row = connection.execute(
            sql.text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name = :table AND table_schema = :schema"
            ),
            {"table": table_name, "schema": schema or "public"},
        ).scalar()
        return row > 0

    def has_sequence(self, connection, sequence_name, schema=None, **kw):
        row = connection.execute(
            sql.text(
                "SELECT COUNT(*) FROM information_schema.sequences "
                "WHERE sequence_name = :seq AND sequence_schema = :schema"
            ),
            {"seq": sequence_name, "schema": schema or "public"},
        ).scalar()
        return row > 0

    def get_default_schema_name(self, connection):
        row = connection.execute(sql.text("SELECT CURRENT_SCHEMA")).scalar()
        return row or "public"

    def do_rollback(self, dbapi_connection):
        pass

    def do_commit(self, dbapi_connection):
        pass

    get_schema_names = get_schema_names
    get_table_names = get_table_names
    get_view_names = get_view_names
    get_columns = get_columns
    get_pk_constraint = get_pk_constraint
    get_foreign_keys = _empty_constraints
    get_indexes = _empty_constraints
    get_unique_constraints = _empty_constraints
    get_view_definition = get_view_definition
    get_table_comment = get_table_comment


registry.register(
    "vastbase",
    "metadata.ingestion.source.database.customdatabase.vastbase_connector.vastbase_dialect",
    "VastbaseDialect",
)
