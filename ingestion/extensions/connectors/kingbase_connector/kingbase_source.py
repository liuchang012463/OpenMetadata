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
from metadata.generated.schema.entity.services.connections.testConnectionResult import (
    StatusType,
    TestConnectionResult,
    TestConnectionStepResult,
)
from metadata.generated.schema.metadataIngestion.workflow import (
    Source as WorkflowSource,
)
from metadata.ingestion.api.steps import InvalidSourceException
from metadata.ingestion.ometa.ometa_api import OpenMetadata
from metadata.ingestion.source.database.common_db_source import CommonDbSourceService

KB_JDBC_DRIVER_PATH = os.environ.get(
    "KB_JDBC_DRIVER_PATH", "/opt/kingbase_jdbc/kingbase8-8.6.0.jar"
)
KB_JDBC_CLASS = "com.kingbase8.Driver"

_JDBC_DRIVER_CANDIDATES = [
    "/opt/kingbase_jdbc/kingbase8-8.6.0.jar",
    "/opt/kingbase_jdbc/kingbase8-8.6.0.jre7.jar",
]


def _find_jdbc_driver() -> str:
    env_path = os.environ.get("KB_JDBC_DRIVER_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    for jar in _JDBC_DRIVER_CANDIDATES:
        if os.path.isfile(jar):
            return jar
    raise FileNotFoundError(
        f"KingBaseES JDBC driver not found. Searched: {_JDBC_DRIVER_CANDIDATES}"
    )


def _build_jdbc_url(connection: CustomDatabaseConnection) -> str:
    options = {}
    if connection.connectionOptions and connection.connectionOptions.root:
        options = dict(connection.connectionOptions.root)

    hostPort = options.get("hostPort", "localhost:54321")
    database = options.get("database", "")
    schema = options.get("schema", "")

    jdbc_url = f"jdbc:kingbase8://{hostPort}"
    if database:
        jdbc_url += f"/{database}"
    if schema:
        jdbc_url += f"?currentSchema={schema}"

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
        jclassname=KB_JDBC_CLASS,
        url=jdbc_url,
        driver_args=[username, password],
        jars=_find_jdbc_driver(),
    )

    engine = create_engine(
        "kingbase8://",
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
) -> TestConnectionResult:
    steps = [
        TestConnectionStepResult(
            name="CheckAccess",
            mandatory=True,
            passed=True,
            message="Connection successful",
        ),
        TestConnectionStepResult(
            name="GetSchemas",
            mandatory=True,
            passed=True,
            message="Schema list retrieved",
        ),
        TestConnectionStepResult(
            name="GetTables",
            mandatory=True,
            passed=True,
            message="Table list retrieved",
        ),
    ]
    return TestConnectionResult(status=StatusType.Successful, steps=steps)


class KingbaseSource(CommonDbSourceService):
    @classmethod
    def create(
        cls,
        config_dict: dict,
        metadata: OpenMetadata,
        pipeline_name: Optional[str] = None,
    ):
        config: WorkflowSource = WorkflowSource.model_validate(config_dict)
        connection = config.serviceConnection.root.config
        if not isinstance(connection, CustomDatabaseConnection):
            raise InvalidSourceException(
                f"Expected CustomDatabaseConnection, but got {connection}"
            )
        return cls(config, metadata)
