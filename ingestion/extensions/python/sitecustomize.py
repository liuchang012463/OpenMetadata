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

"""Bootstrap a one-directory OpenMetadata ingestion extension bundle."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

EXTENSION_ROOT = Path(
    os.environ.get("OPENMETADATA_EXTENSION_ROOT", "/opt/om-extensions")
).resolve()
PYTHON_ROOT = EXTENSION_ROOT / "python"
CONNECTOR_ROOT = EXTENSION_ROOT / "connectors"
DATABASE_EXTENSION_ROOT = PYTHON_ROOT / "metadata" / "ingestion" / "source" / "database"


def _prepend_path(path: Path) -> None:
    value = str(path)
    if path.is_dir() and value not in sys.path:
        sys.path.insert(0, value)


def _set_default_driver_path(variable: str, relative_path: str) -> None:
    path = EXTENSION_ROOT / relative_path
    if path.is_file():
        os.environ.setdefault(variable, str(path))


if EXTENSION_ROOT.is_dir():
    # The mounted bundle carries both third-party Python packages and legacy
    # top-level connector packages.  New connectors can be added below the
    # same directories without changing the container image.
    _prepend_path(PYTHON_ROOT)
    _prepend_path(CONNECTOR_ROOT)

    os.environ.setdefault("OPENMETADATA_EXTENSION_ROOT", str(EXTENSION_ROOT))
    _set_default_driver_path("DM_JDBC_DRIVER_PATH", "drivers/dameng/DmJdbcDriver8.jar")
    _set_default_driver_path(
        "KB_JDBC_DRIVER_PATH", "drivers/kingbase/kingbase8-8.6.0.jar"
    )
    _set_default_driver_path(
        "VASTBASE_JDBC_DRIVER_PATH",
        "drivers/vastbase/Vastbase-G100-2.16_pg_2026062910.jar",
    )

    # OpenMetadata's metadata package is supplied by the base image.  Extend
    # only the database package path so the mounted CustomDatabase package is
    # discovered without shadowing the rest of OpenMetadata.
    if DATABASE_EXTENSION_ROOT.is_dir():
        database_package = importlib.import_module("metadata.ingestion.source.database")
        database_package.__path__ = [
            str(DATABASE_EXTENSION_ROOT),
            *list(database_package.__path__),
        ]
