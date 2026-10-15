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
from sqlalchemy.dialects import postgresql as pg_types
from sqlalchemy.dialects import registry
from sqlalchemy.engine import reflection
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.sql import sqltypes
from sqlalchemy.types import UserDefinedType

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

# PostgreSQL object-identifier types: unsigned 32-bit integers that the
# catalog reports under their own names.
_OID_TYPES = frozenset(
    {
        "OID",
        "XID",
        "CID",
        "REGCLASS",
        "REGTYPE",
        "REGPROC",
        "REGPROCEDURE",
        "REGOPER",
        "REGOPERATOR",
        "REGNAMESPACE",
        "REGCONFIG",
        "REGDICTIONARY",
    }
)

# Geometric and XML types have no SQLAlchemy generic equivalent, so they are
# rendered under their PostgreSQL name; OpenMetadata resolves that name
# through the same _SOURCE_TYPE_TO_OM_TYPE table it uses for native PostgreSQL
# (POINT -> GEOMETRY, XML -> XML).
_NAMED_TYPES = frozenset(
    {"XML", "POINT", "LINE", "LSEG", "BOX", "PATH", "POLYGON", "CIRCLE"}
)

_ARRAY_ELEMENT_TYPES = {
    "int2": sqltypes.SMALLINT,
    "int4": sqltypes.INTEGER,
    "int8": sqltypes.BIGINT,
    "float4": sqltypes.REAL,
    "float8": sqltypes.FLOAT,
    "numeric": sqltypes.NUMERIC,
    "bool": sqltypes.BOOLEAN,
    "text": sqltypes.TEXT,
    "varchar": sqltypes.VARCHAR,
    "bpchar": sqltypes.CHAR,
    "name": sqltypes.String,
    "date": sqltypes.DATE,
    "timestamp": sqltypes.DATETIME,
    "timestamptz": sqltypes.TIMESTAMP,
    "time": sqltypes.TIME,
    "timetz": sqltypes.TIME,
    "uuid": sqltypes.Uuid,
    "json": sqltypes.JSON,
    "jsonb": sqltypes.JSON,
    "bytea": sqltypes.BLOB,
}


class _PostgresNamedType(UserDefinedType):
    """Renders a fixed type name for OpenMetadata's name-based lookup."""

    def __init__(self, name: str):
        self.name = name

    def get_col_spec(self, **kw):
        return self.name

    def __str__(self):
        return self.name


def _column_type(data_type, raw_length, precision, scale, udt_name=None):
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
    if data_type == "NAME":
        return sqltypes.String(length=length)
    if data_type in _OID_TYPES:
        return sqltypes.BIGINT()
    if data_type in _NAMED_TYPES:
        return _PostgresNamedType(data_type)
    if data_type == "ARRAY":
        element = _ARRAY_ELEMENT_TYPES.get(str(udt_name or "").lstrip("_").lower())
        return sqltypes.ARRAY(element()) if element else sqltypes.NullType()
    if data_type in ("FLOAT", "DOUBLE", "DOUBLE PRECISION"):
        return sqltypes.FLOAT()
    if data_type == "REAL":
        return sqltypes.REAL()
    if data_type in ("DECIMAL", "NUMERIC", "NUMBER"):
        return sqltypes.NUMERIC(precision=precision, scale=scale)
    if data_type == "MONEY":
        return sqltypes.NUMERIC()
    if data_type == "DATE":
        return sqltypes.DATE()
    if data_type in ("TIMESTAMP", "TIMESTAMP WITHOUT TIME ZONE", "DATETIME"):
        return sqltypes.DATETIME()
    if data_type in ("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ"):
        return sqltypes.TIMESTAMP()
    if data_type in ("TIME", "TIME WITHOUT TIME ZONE"):
        return sqltypes.TIME()
    if data_type in ("TIME WITH TIME ZONE", "TIMETZ"):
        return pg_types.TIME(timezone=True)
    if data_type in ("INTERVAL",):
        return pg_types.INTERVAL()
    if data_type in ("BOOLEAN", "BOOL", "BIT"):
        return sqltypes.BOOLEAN()
    if data_type in ("BIT VARYING", "VARBIT"):
        return pg_types.BIT(varying=True)
    if data_type in ("BYTEA", "BLOB"):
        return sqltypes.BLOB()
    if data_type in ("TEXT", "CLOB"):
        return sqltypes.TEXT()
    if data_type == "JSON":
        return sqltypes.JSON()
    if data_type == "JSONB":
        return pg_types.JSONB()
    if data_type == "TSVECTOR":
        return pg_types.TSVECTOR()
    if data_type in ("INET", "CIDR", "MACADDR", "MACADDR8"):
        return getattr(pg_types, data_type)()
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
            "c.column_default, c.ordinal_position, c.udt_name, "
            "pgd.description AS comment, "
            "format_type(a.atttypid, a.atttypmod) AS formatted_type "
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
                "type": _column_type(row[1], row[2], row[3], row[4], row[8]),
                "nullable": row[5] == "YES",
                "default": row[6],
                "autoincrement": False,
                "comment": row[9],
                "ordinalPosition": row[7],
                # OpenMetadata builds dataTypeDisplay from the SQLAlchemy type,
                # which renders "varchar(50)" for a "character varying(50)"
                # column. Expose format_type() so the UI shows the type the
                # database itself reports, the way the ClickHouse connector
                # does with its raw type.
                "display_type": row[10],
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
