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


import os
from typing import Optional

import dameng_connector.dm_dialect  # noqa: F401
import jaydebeapi
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

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

DM_JDBC_DRIVER_PATH = os.environ.get(
    "DM_JDBC_DRIVER_PATH", "/opt/dameng_jdbc/DmJdbcDriver8.jar"
)
DM_JDBC_CLASS = "dm.jdbc.driver.DmDriver"

_JDBC_DRIVER_CANDIDATES = [
    "/opt/dameng_jdbc/DmJdbcDriver8.jar",
    "/opt/dameng_jdbc/DmJdbcDriver11.jar",
    "/opt/dameng_jdbc/DmJdbcDriver7.jar",
    "/opt/dameng_jdbc/DmJdbcDriver6.jar",
]


def _find_jdbc_driver() -> str:
    env_path = os.environ.get("DM_JDBC_DRIVER_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    for jar in _JDBC_DRIVER_CANDIDATES:
        if os.path.isfile(jar):
            return jar
    raise FileNotFoundError(
        f"DaMeng JDBC driver not found. Searched: {_JDBC_DRIVER_CANDIDATES}"
    )


def _build_jdbc_url(connection: CustomDatabaseConnection) -> str:
    options = {}
    if connection.connectionOptions and connection.connectionOptions.root:
        options = dict(connection.connectionOptions.root)

    hostPort = options.get("hostPort", "")
    database = options.get("database", "")
    schema = options.get("schema", "")

    jdbc_url = f"jdbc:dm://{hostPort}"
    if database:
        jdbc_url += f"/{database}"
    if schema:
        jdbc_url += f"?schema={schema}"

    return jdbc_url


def _get_credentials(connection: CustomDatabaseConnection):
    options = {}
    if connection.connectionOptions and connection.connectionOptions.root:
        options = dict(connection.connectionOptions.root)

    username = options.get("username", "")
    password = options.get("password", "")
    return username, password


def get_connection(connection: CustomDatabaseConnection) -> Engine:
    jdbc_url = _build_jdbc_url(connection)
    username, password = _get_credentials(connection)

    conn = jaydebeapi.connect(
        jclassname=DM_JDBC_CLASS,
        url=jdbc_url,
        driver_args=[username, password],
        jars=_find_jdbc_driver(),
    )

    engine = create_engine(
        "dm://",
        creator=lambda: conn,
        module=jaydebeapi,
        poolclass=QueuePool,
        pool_reset_on_return=None,
        echo=False,
        max_overflow=-1,
    )
    return engine


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
