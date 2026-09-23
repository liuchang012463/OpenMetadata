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


"""Vastbase JDBC connection adapter for OpenMetadata 1.12.10."""

import os
from pathlib import Path
from typing import Optional

import jaydebeapi
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

import metadata.ingestion.source.database.customdatabase.vastbase_connector.vastbase_dialect
from metadata.generated.schema.entity.automations.workflow import (
    Workflow as AutomationWorkflow,
)
from metadata.generated.schema.entity.services.connections.database.customDatabaseConnection import (
    CustomDatabaseConnection,
)
from metadata.ingestion.connections.test_connections import (
    test_connection_db_schema_sources,
)
from metadata.ingestion.ometa.ometa_api import OpenMetadata

VASTBASE_JDBC_CLASS = "org.postgresql.Driver"
VASTBASE_JDBC_DRIVER_NAME = "Vastbase-G100-2.16_pg_2026062910.jar"


def _find_jdbc_driver() -> str:
    env_path = os.environ.get("VASTBASE_JDBC_DRIVER_PATH")
    package_driver_dir = Path(__file__).resolve().parent / "drivers"
    candidates = [
        env_path,
        str(package_driver_dir / VASTBASE_JDBC_DRIVER_NAME),
        "/opt/vastbase_jdbc/Vastbase-G100-2.16_pg_2026062910.jar",
    ]
    candidates.extend(str(path) for path in sorted(package_driver_dir.glob("*.jar")))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError(
        "Vastbase JDBC driver not found. Searched: "
        + ", ".join(path for path in candidates if path)
    )


def _connection_options(connection: CustomDatabaseConnection) -> dict:
    if connection.connectionOptions and connection.connectionOptions.root:
        return dict(connection.connectionOptions.root)
    return {}


def _build_jdbc_url(connection: CustomDatabaseConnection) -> str:
    options = _connection_options(connection)
    host_port = options.get("hostPort", "localhost:5432")
    database = options.get("database", "")
    schema = options.get("schema", "")
    jdbc_url = f"jdbc:postgresql://{host_port}"
    if database:
        jdbc_url += f"/{database}"
    if schema:
        jdbc_url += f"?currentSchema={schema}"
    return jdbc_url


def _open_jdbc_connection(connection: CustomDatabaseConnection):
    options = _connection_options(connection)
    return jaydebeapi.connect(
        jclassname=VASTBASE_JDBC_CLASS,
        url=_build_jdbc_url(connection),
        driver_args=[options.get("username", ""), options.get("password", "")],
        jars=_find_jdbc_driver(),
    )


def get_connection(connection: CustomDatabaseConnection) -> Engine:
    # JPype can start only one JVM per Python process.  OpenMetadata's
    # profiler may check out several SQLAlchemy connections, but JPype can
    # start only one JVM per Python process. Keep one vendor-driver connection
    # and expose it through StaticPool so a second checkout never invokes
    # JayDeBeApi again and triggers ``JVM is already started``.
    jdbc_connection = _open_jdbc_connection(connection)
    return create_engine(
        "vastbase://",
        creator=lambda: jdbc_connection,
        module=jaydebeapi,
        poolclass=StaticPool,
        pool_reset_on_return=None,
        echo=False,
    )


def test_connection(
    metadata: OpenMetadata,
    engine: Engine,
    service_connection: CustomDatabaseConnection,
    automation_workflow: Optional[AutomationWorkflow] = None,
) -> None:
    test_connection_db_schema_sources(
        metadata=metadata,
        engine=engine,
        service_connection=service_connection,
        automation_workflow=automation_workflow,
    )
