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


from sqlalchemy import sql
from sqlalchemy.dialects import registry
from sqlalchemy.engine import reflection
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.exc import CompileError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql import sqltypes

from metadata.profiler.orm.functions.median import MedianFn
from metadata.profiler.orm.functions.modulo import ModuloFn
from metadata.profiler.orm.functions.random_num import RandomNumFn


@compiles(RandomNumFn, "dm")
def compile_dameng_random_num(elements, compiler, **kwargs):
    """Use Dameng's RAND() function for randomized profiler sampling."""
    return "ABS(RAND()) * 100"


@compiles(ModuloFn, "dm")
def compile_dameng_modulo(elements, compiler, **kwargs):
    """Compile modulo through Dameng's MOD function."""
    left, right = [compiler.process(element, **kwargs) for element in elements.clauses]
    return f"MOD({left}, {right})"


@compiles(MedianFn, "dm")
def compile_dameng_median(elements, compiler, **kwargs):
    """Compile percentile metrics using Dameng's analytic-function syntax."""
    clauses = elements.clauses.clauses
    column = compiler.process(clauses[0], **kwargs)
    percentile = clauses[2].value
    dimension_col = clauses[3].value if len(clauses) > 3 else None
    if dimension_col:
        raise CompileError(
            "Dameng median metrics with dimension_col are unsupported by "
            "OpenMetadata 2.0.4's grouped validation query"
        )
    return (
        f"PERCENTILE_CONT({percentile:.2f}) WITHIN GROUP "
        f"(ORDER BY {column} ASC) OVER()"
    )


@reflection.cache
def get_schema_names(self, connection, **kw):
    rows = connection.execute(sql.text("SELECT USERNAME FROM ALL_USERS ORDER BY USERNAME"))
    return [row[0] for row in rows]


@reflection.cache
def get_table_names(self, connection, schema=None, **kw):
    query = "SELECT TABLE_NAME FROM ALL_TABLES"
    params = {}
    if schema:
        query += " WHERE OWNER = :schema"
        params["schema"] = schema.upper()
    query += " ORDER BY TABLE_NAME"
    rows = connection.execute(sql.text(query), params)
    return [row[0] for row in rows]


@reflection.cache
def get_view_names(self, connection, schema=None, **kw):
    query = "SELECT VIEW_NAME FROM ALL_VIEWS"
    params = {}
    if schema:
        query += " WHERE OWNER = :schema"
        params["schema"] = schema.upper()
    query += " ORDER BY VIEW_NAME"
    rows = connection.execute(sql.text(query), params)
    return [row[0] for row in rows]


@reflection.cache
def get_columns(self, connection, table_name, schema=None, **kw):
    query = """SELECT c.COLUMN_NAME, c.DATA_TYPE, c.DATA_LENGTH, c.DATA_PRECISION,
                      c.DATA_SCALE, c.NULLABLE, c.COLUMN_ID, c.DATA_DEFAULT,
                      cc.COMMENTS, c.CHAR_LENGTH
               FROM ALL_TAB_COLUMNS c
               LEFT JOIN ALL_COL_COMMENTS cc
                      ON cc.OWNER = c.OWNER
                     AND cc.TABLE_NAME = c.TABLE_NAME
                     AND cc.COLUMN_NAME = c.COLUMN_NAME
               WHERE c.TABLE_NAME = :table"""
    params = {"table": table_name.upper()}
    if schema:
        query += " AND c.OWNER = :schema"
        params["schema"] = schema.upper()
    query += " ORDER BY c.COLUMN_ID"
    rows = connection.execute(sql.text(query), params)
    columns = []
    for row in rows:
        col_type = _col_type(
            row[1], row[3], row[4], char_length=row[9], data_length=row[2]
        )
        columns.append(
            {
                "name": row[0],
                "type": col_type,
                "nullable": row[5] == "Y",
                "default": row[7],
                "autoincrement": False,
                "comment": row[8],
                "ordinalPosition": row[6],
            }
        )
    return columns


_CHARACTER_TYPES = frozenset(
    {
        "VARCHAR",
        "VARCHAR2",
        "CHARACTER VARYING",
        "CHAR",
        "CHARACTER",
        "NCHAR",
        "NVARCHAR",
        "NVARCHAR2",
        "LONGVARCHAR",
    }
)

_BINARY_TYPES = frozenset({"BINARY", "VARBINARY", "LONGVARBINARY"})


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _declared_length(data_type, char_length, data_length):
    """Length to attach to the SQLAlchemy type.

    Dameng reports DATA_LENGTH in *bytes* for the N-types (four bytes per
    character) and stores the row width there for every other type, so only
    CHAR_LENGTH carries the declared length of a character column. Binary
    columns have no character length and use DATA_LENGTH directly.
    """
    if data_type in _CHARACTER_TYPES:
        return _to_int(char_length) or _to_int(data_length)
    if data_type in _BINARY_TYPES:
        return _to_int(data_length)
    return None


def _col_type(data_type, precision, scale, char_length=None, data_length=None):
    t = str(data_type).upper()
    length = _declared_length(t, char_length, data_length)
    if t in ("INT", "INTEGER"):
        return sqltypes.INTEGER()
    elif t in ("BIGINT",):
        return sqltypes.BIGINT()
    elif t in ("SMALLINT", "BYTE"):
        return sqltypes.SMALLINT()
    elif t in ("TINYINT",):
        return sqltypes.SMALLINT()
    elif t in ("VARCHAR", "VARCHAR2", "CHARACTER VARYING", "ROWID", "UROWID"):
        return sqltypes.VARCHAR(length=length)
    elif t in ("NVARCHAR", "NVARCHAR2"):
        return sqltypes.NVARCHAR(length=length)
    elif t in ("CHAR", "CHARACTER"):
        return sqltypes.CHAR(length=length)
    elif t in ("NCHAR",):
        return sqltypes.NCHAR(length=length)
    elif t in ("FLOAT",):
        return sqltypes.FLOAT()
    elif t in ("DOUBLE", "DOUBLE PRECISION"):
        return sqltypes.FLOAT()
    elif t in ("REAL",):
        return sqltypes.REAL()
    elif t in ("DEC", "DECIMAL", "NUMERIC", "NUMBER"):
        return sqltypes.NUMERIC(precision=precision, scale=scale)
    elif t in ("DATE",):
        return sqltypes.DATE()
    elif t in ("TIMESTAMP", "DATETIME"):
        return sqltypes.DATETIME()
    elif t in ("TIME",):
        return sqltypes.TIME()
    elif t in ("BLOB", "IMAGE"):
        return sqltypes.BLOB()
    elif t in ("CLOB", "TEXT", "LONG"):
        return sqltypes.TEXT()
    elif t in ("BINARY",):
        return sqltypes.BINARY(length=length)
    elif t in ("VARBINARY",):
        return sqltypes.VARBINARY(length=length)
    elif t in ("BIT", "BOOLEAN"):
        return sqltypes.BOOLEAN()
    else:
        return sqltypes.NullType()


@reflection.cache
def get_pk_constraint(self, connection, table_name, schema=None, **kw):
    query = """SELECT cons.CONSTRAINT_NAME, cols.COLUMN_NAME
               FROM ALL_CONSTRAINTS cons
               JOIN ALL_CONS_COLUMNS cols ON cons.CONSTRAINT_NAME = cols.CONSTRAINT_NAME
                     AND cons.OWNER = cols.OWNER
               WHERE cons.TABLE_NAME = :table AND cons.CONSTRAINT_TYPE = 'P'"""
    params = {"table": table_name.upper()}
    if schema:
        query += " AND cons.OWNER = :schema"
        params["schema"] = schema.upper()
    query += " ORDER BY cols.POSITION"
    rows = connection.execute(sql.text(query), params)
    rows = list(rows)
    return {
        "constrained_columns": [row[1] for row in rows],
        "name": rows[0][0] if rows else None,
    }


@reflection.cache
def get_foreign_keys(self, connection, table_name, schema=None, **kw):
    query = """SELECT cons.CONSTRAINT_NAME, cols.COLUMN_NAME, rcons.OWNER,
                      rcons.TABLE_NAME, rcols.COLUMN_NAME
               FROM ALL_CONSTRAINTS cons
               JOIN ALL_CONS_COLUMNS cols ON cons.CONSTRAINT_NAME = cols.CONSTRAINT_NAME
                     AND cons.OWNER = cols.OWNER
               JOIN ALL_CONSTRAINTS rcons ON cons.R_CONSTRAINT_NAME = rcons.CONSTRAINT_NAME
                     AND rcons.OWNER = cons.R_OWNER
               JOIN ALL_CONS_COLUMNS rcols ON rcons.CONSTRAINT_NAME = rcols.CONSTRAINT_NAME
                     AND rcols.OWNER = rcons.OWNER AND rcols.POSITION = cols.POSITION
               WHERE cons.CONSTRAINT_TYPE = 'R' AND cons.TABLE_NAME = :table"""
    params = {"table": table_name.upper()}
    if schema:
        query += " AND cons.OWNER = :schema"
        params["schema"] = schema.upper()
    query += " ORDER BY cons.CONSTRAINT_NAME, cols.POSITION"
    rows = connection.execute(sql.text(query), params)
    return [
        {
            "name": name,
            "constrained_columns": [row[1] for row in group],
            "referred_schema": group[0][2],
            "referred_table": group[0][3],
            "referred_columns": [row[4] for row in group],
        }
        for name, group in _group_by_name(rows).items()
    ]


@reflection.cache
def get_indexes(self, connection, table_name, schema=None, **kw):
    query = """SELECT ind.INDEX_NAME, ind.UNIQUENESS, cols.COLUMN_NAME
               FROM ALL_INDEXES ind
               JOIN ALL_IND_COLUMNS cols ON cols.INDEX_NAME = ind.INDEX_NAME
                     AND cols.TABLE_OWNER = ind.OWNER
               WHERE ind.TABLE_NAME = :table"""
    params = {"table": table_name.upper()}
    if schema:
        query += " AND ind.OWNER = :schema"
        params["schema"] = schema.upper()
    query += " ORDER BY ind.INDEX_NAME, cols.COLUMN_POSITION"
    rows = connection.execute(sql.text(query), params)
    return [
        {
            "name": name,
            "unique": group[0][1] == "UNIQUE",
            "column_names": [row[2] for row in group],
        }
        for name, group in _group_by_name(rows).items()
    ]


@reflection.cache
def get_unique_constraints(self, connection, table_name, schema=None, **kw):
    query = """SELECT cons.CONSTRAINT_NAME, cols.COLUMN_NAME
               FROM ALL_CONSTRAINTS cons
               JOIN ALL_CONS_COLUMNS cols ON cons.CONSTRAINT_NAME = cols.CONSTRAINT_NAME
                     AND cons.OWNER = cols.OWNER
               WHERE cons.CONSTRAINT_TYPE = 'U' AND cons.TABLE_NAME = :table"""
    params = {"table": table_name.upper()}
    if schema:
        query += " AND cons.OWNER = :schema"
        params["schema"] = schema.upper()
    query += " ORDER BY cons.CONSTRAINT_NAME, cols.POSITION"
    rows = connection.execute(sql.text(query), params)
    return [
        {"name": name, "column_names": [row[1] for row in group]}
        for name, group in _group_by_name(rows).items()
    ]


def _group_by_name(rows):
    """Fold one row per column into one entry per constraint or index."""
    grouped = {}
    for row in rows:
        grouped.setdefault(row[0], []).append(row)
    return grouped


@reflection.cache
def get_view_definition(self, connection, view_name, schema=None, **kw):
    query = "SELECT TEXT FROM ALL_VIEWS WHERE VIEW_NAME = :view"
    params = {"view": view_name.upper()}
    if schema:
        query += " AND OWNER = :schema"
        params["schema"] = schema.upper()
    row = connection.execute(sql.text(query), params).fetchone()
    return row[0] if row else None


@reflection.cache
def get_table_comment(self, connection, table_name, schema=None, **kw):
    query = "SELECT COMMENTS FROM ALL_TAB_COMMENTS WHERE TABLE_NAME = :table"
    params = {"table": table_name.upper()}
    if schema:
        query += " AND OWNER = :schema"
        params["schema"] = schema.upper()
    row = connection.execute(sql.text(query), params).fetchone()
    return {"text": row[0] if row else None}


class DamengSQLCompiler(SQLCompiler):
    """Compile SQLAlchemy row limits using Dameng's SQL syntax."""

    def limit_clause(self, select, **kwargs):
        text = ""
        limit_clause = select._limit_clause
        offset_clause = select._offset_clause

        if offset_clause is not None:
            if not select._simple_int_clause(offset_clause):
                raise CompileError("Dameng only supports simple integer OFFSET values")
            offset = self.process(offset_clause.render_literal_execute(), **kwargs)
            text += f"\n OFFSET {offset} ROWS"

        if limit_clause is not None:
            if not select._simple_int_clause(limit_clause):
                raise CompileError("Dameng only supports simple integer LIMIT values")
            limit = self.process(limit_clause.render_literal_execute(), **kwargs)
            text += f"\n FETCH FIRST {limit} ROWS ONLY"

        return text


class DamengDialect(DefaultDialect):
    name = "dm"
    statement_compiler = DamengSQLCompiler
    supports_statement_cache = True
    supports_alter = True
    supports_pk_autoincrement = True
    supports_schemas = True
    supports_sequences = True
    supports_native_boolean = False
    supports_native_decimal = True
    supports_native_enum = False
    supports_native_uuid = False
    returns_native_bytes = False
    description_encoding = None
    server_version_info = None
    default_schema_name = None
    supports_comments = True

    def initialize(self, connection):
        self.server_version_info = None

    def has_table(self, connection, table_name, schema=None, **kw):
        query = "SELECT COUNT(*) FROM ALL_TABLES WHERE TABLE_NAME = :table"
        params = {"table": table_name.upper()}
        if schema:
            query += " AND OWNER = :schema"
            params["schema"] = schema.upper()
        row = connection.execute(sql.text(query), params).scalar()
        return row > 0

    def has_sequence(self, connection, sequence_name, schema=None, **kw):
        query = "SELECT COUNT(*) FROM ALL_SEQUENCES WHERE SEQUENCE_NAME = :seq"
        params = {"seq": sequence_name.upper()}
        if schema:
            query += " AND SEQUENCE_OWNER = :schema"
            params["schema"] = schema.upper()
        row = connection.execute(sql.text(query), params).scalar()
        return row > 0

    def get_default_schema_name(self, connection):
        row = connection.execute(sql.text("SELECT USER FROM DUAL")).scalar()
        return row

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


registry.register("dm", "dameng_connector.dm_dialect", "DamengDialect")
