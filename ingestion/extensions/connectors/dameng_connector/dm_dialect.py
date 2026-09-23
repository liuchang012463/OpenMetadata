# Copyright 2026 Collate
# Licensed under the Collate Community License, Version 1.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# https://github.com/open-metadata/OpenMetadata/blob/1.12.10/ingestion/LICENSE
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from sqlalchemy import sql
from sqlalchemy.dialects import registry
from sqlalchemy.engine import reflection
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.sql import sqltypes


@reflection.cache
def get_schema_names(self, connection, **kw):
    rows = connection.execute("SELECT USERNAME FROM ALL_USERS ORDER BY USERNAME")
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
    query = """SELECT COLUMN_NAME, DATA_TYPE, DATA_LENGTH, DATA_PRECISION,
                      DATA_SCALE, NULLABLE, COLUMN_ID, DATA_DEFAULT
               FROM ALL_TAB_COLUMNS
               WHERE TABLE_NAME = :table"""
    params = {"table": table_name.upper()}
    if schema:
        query += " AND OWNER = :schema"
        params["schema"] = schema.upper()
    query += " ORDER BY COLUMN_ID"
    rows = connection.execute(sql.text(query), params)
    columns = []
    for row in rows:
        col_type = _col_type(row[1], row[3], row[4])
        columns.append(
            {
                "name": row[0],
                "type": col_type,
                "nullable": row[5] == "Y",
                "default": row[7],
                "autoincrement": False,
                "comment": None,
            }
        )
    return columns


def _col_type(data_type, precision, scale):
    t = data_type.upper()
    if t in ("INT", "INTEGER"):
        return sqltypes.INTEGER()
    elif t in ("BIGINT",):
        return sqltypes.BIGINT()
    elif t in ("SMALLINT",):
        return sqltypes.SMALLINT()
    elif t in ("TINYINT",):
        return sqltypes.SMALLINT()
    elif t in ("VARCHAR", "VARCHAR2", "CHARACTER VARYING"):
        return sqltypes.VARCHAR()
    elif t in ("NVARCHAR", "NVARCHAR2"):
        return sqltypes.NVARCHAR()
    elif t in ("CHAR", "CHARACTER"):
        return sqltypes.CHAR()
    elif t in ("NCHAR",):
        return sqltypes.NCHAR()
    elif t in ("FLOAT",):
        return sqltypes.FLOAT()
    elif t in ("DOUBLE", "DOUBLE PRECISION"):
        return sqltypes.FLOAT()
    elif t in ("REAL",):
        return sqltypes.REAL()
    elif t in ("DEC", "DECIMAL", "NUMERIC", "NUMBER"):
        return sqltypes.NUMERIC()
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
    elif t in ("BINARY", "VARBINARY"):
        return sqltypes.VARBINARY()
    elif t in ("BIT", "BOOLEAN"):
        return sqltypes.BOOLEAN()
    else:
        return sqltypes.NullType()


@reflection.cache
def get_pk_constraint(self, connection, table_name, schema=None, **kw):
    query = """SELECT cols.COLUMN_NAME
               FROM ALL_CONSTRAINTS cons
               JOIN ALL_CONS_COLUMNS cols ON cons.CONSTRAINT_NAME = cols.CONSTRAINT_NAME
               WHERE cons.TABLE_NAME = :table AND cons.CONSTRAINT_TYPE = 'P'"""
    params = {"table": table_name.upper()}
    if schema:
        query += " AND cons.OWNER = :schema"
        params["schema"] = schema.upper()
    rows = connection.execute(sql.text(query), params)
    cols = [row[0] for row in rows]
    return {"constrained_columns": cols, "name": None}


@reflection.cache
def get_foreign_keys(self, connection, table_name, schema=None, **kw):
    return []


@reflection.cache
def get_indexes(self, connection, table_name, schema=None, **kw):
    query = """SELECT cols.COLUMN_NAME, ind.UNIQUENESS
               FROM ALL_IND_COLUMNS cols
               JOIN ALL_INDEXES ind ON cols.INDEX_NAME = ind.INDEX_NAME
               WHERE cols.TABLE_NAME = :table"""
    params = {"table": table_name.upper()}
    if schema:
        query += " AND cols.TABLE_OWNER = :schema"
        params["schema"] = schema.upper()
    query += " ORDER BY cols.COLUMN_POSITION"
    rows = connection.execute(sql.text(query), params)
    cols = []
    unique = False
    for row in rows:
        cols.append(row[0])
        if row[1] == "UNIQUE":
            unique = True
    if cols:
        return [{"name": None, "unique": unique, "column_names": cols}]
    return []


@reflection.cache
def get_unique_constraints(self, connection, table_name, schema=None, **kw):
    return []


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


class DamengDialect(DefaultDialect):
    name = "dm"
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
        row = connection.execute("SELECT USER FROM DUAL").scalar()
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
