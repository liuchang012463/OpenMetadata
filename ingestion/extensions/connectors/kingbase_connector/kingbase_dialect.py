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


import re

from sqlalchemy import sql
from sqlalchemy.dialects import registry
from sqlalchemy.engine import reflection
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import sqltypes

from metadata.profiler.orm.functions.modulo import ModuloFn
from metadata.profiler.orm.functions.length import LenFn
from metadata.profiler.orm.functions.random_num import RandomNumFn

EXCLUDED_SCHEMAS = frozenset(
    {
        "sysmac",
        "pg_catalog",
        "information_schema",
        "pg_toast",
        "pg_bitmapindex",
        "pg_temp_1",
        "pg_toast_temp_1",
    }
)


@compiles(RandomNumFn, "kingbase8")
def compile_kingbase_random_num(elements, compiler, **kwargs):
    return "ABS((RANDOM() * 100)::INTEGER)"


@compiles(ModuloFn, "kingbase8")
def compile_kingbase_modulo(element, compiler, **kwargs):
    if len(element.clauses) != 2:
        raise ValueError("We need two elements to compute the modulo")
    value, base = [compiler.process(part, **kwargs) for part in element.clauses]
    return f"MOD({value}, {base})"


@compiles(LenFn, "kingbase8")
def compile_kingbase_length(element, compiler, **kwargs):
    value = compiler.process(element.clauses, **kwargs)
    return f"LENGTH(CAST({value} AS TEXT))"


def _parse_kingbase_length(raw: str | None) -> int | None:
    if raw is None:
        return None
    m = re.match(r"(\d+)", str(raw))
    return int(m.group(1)) if m else None


def _parse_kingbase_format_length(formatted_type: str | None) -> int | None:
    """Length out of a format_type() rendering such as
    "character varying(32 byte)". Returns None when the rendering carries no
    length, e.g. "varchar" or "text"."""
    if formatted_type is None:
        return None
    m = re.search(r"\(\s*(\d+)", str(formatted_type))
    return int(m.group(1)) if m else None


@reflection.cache
def get_schema_names(self, connection, **kw):
    rows = connection.execute(
        sql.text(
            "SELECT schema_name FROM information_schema.schemata "
            "ORDER BY schema_name"
        )
    )
    return [row[0] for row in rows if row[0] not in EXCLUDED_SCHEMAS]


@reflection.cache
def get_table_names(self, connection, schema=None, **kw):
    query = "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
    params = {"schema": schema or "public"}
    rows = connection.execute(sql.text(query), params)
    return [row[0] for row in rows]


@reflection.cache
def get_view_names(self, connection, schema=None, **kw):
    query = "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema AND table_type = 'VIEW'"
    params = {"schema": schema or "public"}
    rows = connection.execute(sql.text(query), params)
    return [row[0] for row in rows]


@reflection.cache
def get_columns(self, connection, table_name, schema=None, **kw):
    query = """
        SELECT c.column_name, c.data_type, c.character_maximum_length,
               c.numeric_precision, c.numeric_scale, c.is_nullable,
               c.column_default, c.ordinal_position, c.udt_name,
               format_type(a.atttypid, a.atttypmod) AS formatted_type,
               pgd.description AS comment
        FROM information_schema.columns c
        LEFT JOIN pg_catalog.pg_namespace pn
               ON pn.nspname = c.table_schema
        LEFT JOIN pg_catalog.pg_class pc
               ON pc.relnamespace = pn.oid AND pc.relname = c.table_name
        LEFT JOIN pg_catalog.pg_attribute a
               ON a.attrelid = pc.oid
              AND a.attname = c.column_name
              AND NOT a.attisdropped
        LEFT JOIN pg_catalog.pg_description pgd
               ON pgd.objoid = pc.oid AND pgd.objsubid = a.attnum
        WHERE c.table_name = :table AND c.table_schema = :schema
        ORDER BY c.ordinal_position
    """
    params = {"table": table_name, "schema": schema or "public"}
    rows = connection.execute(sql.text(query), params)
    columns = []
    for row in rows:
        columns.append(
            {
                "name": row[0],
                "type": _col_type(row[1], row[2], row[3], row[4], row[8], row[9]),
                "nullable": row[5] == "YES",
                "default": row[6],
                "autoincrement": False,
                "comment": row[10],
                # OpenMetadata builds dataTypeDisplay from the SQLAlchemy type,
                # which renders "varchar(32)" for a "character varying(32 byte)"
                # column.  Expose format_type() so the UI shows the type the
                # database itself reports, the way the ClickHouse connector does.
                "display_type": row[9],
            }
        )
    return columns


def _col_type(data_type, raw_length, precision, scale, udt_name=None, formatted_type=None):
    t = str(data_type).strip().upper()
    udt = str(udt_name).strip().lower() if udt_name is not None else ""
    parsed_len = _parse_kingbase_length(raw_length)
    if parsed_len is None:
        parsed_len = _parse_kingbase_format_length(formatted_type)

    if t == "USER-DEFINED":
        # KingbaseES Oracle mode reports byte-semantics strings declared as
        # (n BYTE) as USER-DEFINED with udt_name varcharbyte / bpcharbyte and
        # no character_maximum_length; only format_type() carries the length.
        if udt == "varcharbyte":
            return sqltypes.VARCHAR(length=parsed_len)
        if udt == "bpcharbyte":
            return sqltypes.CHAR(length=parsed_len)
        formatted = str(formatted_type).strip().lower() if formatted_type else ""
        if formatted.startswith(("character varying", "varchar", "nvarchar")):
            return sqltypes.VARCHAR(length=parsed_len)
        if formatted.startswith(("character", "char", "bpchar")):
            return sqltypes.CHAR(length=parsed_len)
        return sqltypes.NullType()

    if t in ("INTEGER", "INT", "SERIAL"):
        return sqltypes.INTEGER()
    elif t in ("BIGINT", "BIGSERIAL"):
        return sqltypes.BIGINT()
    elif t in ("SMALLINT", "SMALLSERIAL"):
        return sqltypes.SMALLINT()
    elif t == "TINYINT":
        return sqltypes.SMALLINT()
    elif t in ("VARCHAR", "CHARACTER VARYING", "VARCHAR2"):
        return sqltypes.VARCHAR(length=parsed_len)
    elif t in ("NVARCHAR", "NVARCHAR2"):
        return sqltypes.NVARCHAR(length=parsed_len)
    elif t in ("CHAR", "CHARACTER", "BPCHAR"):
        return sqltypes.CHAR(length=parsed_len)
    elif t in ("NCHAR",):
        return sqltypes.NCHAR(length=parsed_len)
    elif t == "FLOAT":
        return sqltypes.FLOAT()
    elif t in ("DOUBLE", "DOUBLE PRECISION"):
        return sqltypes.FLOAT()
    elif t == "REAL":
        return sqltypes.REAL()
    elif t in ("DEC", "DECIMAL", "NUMERIC", "NUMBER"):
        return sqltypes.NUMERIC(precision=precision, scale=scale)
    elif t == "DATE":
        return sqltypes.DATE()
    elif t in ("TIMESTAMP", "DATETIME", "TIMESTAMP WITHOUT TIME ZONE"):
        return sqltypes.DATETIME()
    elif t in ("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ"):
        return sqltypes.TIMESTAMP()
    elif t in ("TIME", "TIME WITHOUT TIME ZONE"):
        return sqltypes.TIME()
    elif t in ("BOOLEAN", "BOOL", "BIT"):
        return sqltypes.BOOLEAN()
    elif t in ("BLOB", "BYTEA"):
        return sqltypes.BLOB()
    elif t in ("CLOB", "TEXT"):
        return sqltypes.TEXT()
    elif t in ("BINARY", "VARBINARY"):
        return sqltypes.VARBINARY()
    elif t == "JSON":
        return sqltypes.JSON()
    elif t == "UUID":
        return sqltypes.Uuid()
    else:
        return sqltypes.NullType()


@reflection.cache
def get_pk_constraint(self, connection, table_name, schema=None, **kw):
    query = """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        WHERE tc.table_name = :table
          AND tc.table_schema = :schema
          AND tc.constraint_type = 'PRIMARY KEY'
        ORDER BY kcu.ordinal_position
    """
    params = {"table": table_name, "schema": schema or "public"}
    rows = connection.execute(sql.text(query), params)
    cols = [row[0] for row in rows]
    return {"constrained_columns": cols, "name": None}


@reflection.cache
def get_foreign_keys(self, connection, table_name, schema=None, **kw):
    return []


@reflection.cache
def get_indexes(self, connection, table_name, schema=None, **kw):
    return []


@reflection.cache
def get_unique_constraints(self, connection, table_name, schema=None, **kw):
    return []


@reflection.cache
def get_view_definition(self, connection, view_name, schema=None, **kw):
    query = """
        SELECT view_definition
        FROM information_schema.views
        WHERE table_name = :view AND table_schema = :schema
    """
    params = {"view": view_name, "schema": schema or "public"}
    row = connection.execute(sql.text(query), params).fetchone()
    return row[0] if row else None


@reflection.cache
def get_table_comment(self, connection, table_name, schema=None, **kw):
    query = """
        SELECT pgd.description
        FROM pg_catalog.pg_description pgd
        JOIN pg_catalog.pg_class pc ON pgd.objoid = pc.oid
        JOIN pg_catalog.pg_namespace pn ON pc.relnamespace = pn.oid
        WHERE pc.relname = :table AND pn.nspname = :schema
          AND pgd.objsubid = 0
        LIMIT 1
    """
    params = {"table": table_name, "schema": schema or "public"}
    row = connection.execute(sql.text(query), params).fetchone()
    return {"text": row[0] if row else None}


class KingbaseDialect(DefaultDialect):
    name = "kingbase8"
    default_paramstyle = "qmark"
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
        query = "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = :table AND table_schema = :schema"
        params = {"table": table_name, "schema": schema or "public"}
        row = connection.execute(sql.text(query), params).scalar()
        return row > 0

    def has_sequence(self, connection, sequence_name, schema=None, **kw):
        query = "SELECT COUNT(*) FROM information_schema.sequences WHERE sequence_name = :seq AND sequence_schema = :schema"
        params = {"seq": sequence_name, "schema": schema or "public"}
        row = connection.execute(sql.text(query), params).scalar()
        return row > 0

    def get_default_schema_name(self, connection):
        row = connection.execute(sql.text("SELECT CURRENT_SCHEMA")).scalar()
        return row or "public"

    def do_rollback(self, dbapi_connection):
        pass

    def do_commit(self, dbapi_connection):
        pass

    def _get_default_schema_name(self, connection):
        return self.get_default_schema_name(connection)

    get_schema_names = get_schema_names
    get_table_names = get_table_names
    get_view_names = get_view_names
    get_columns = get_columns
    get_pk_constraint = get_pk_constraint
    get_foreign_keys = get_foreign_keys
    get_indexes = get_indexes
    get_unique_constraints = get_unique_constraints
    get_view_definition = get_view_definition
    get_table_comment = get_table_comment


registry.register(
    "kingbase8",
    "kingbase_connector.kingbase_dialect",
    "KingbaseDialect",
)
