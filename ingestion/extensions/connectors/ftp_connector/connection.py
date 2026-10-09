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

"""FTP connection helpers for the CustomDrive FTP connector."""

from __future__ import annotations

import io
import stat
import traceback
from dataclasses import dataclass
from ftplib import FTP, error_perm
from typing import List, Optional

from metadata.generated.schema.entity.automations.workflow import (
    Workflow as AutomationWorkflow,
)
from metadata.generated.schema.entity.services.connections.drive.customDriveConnection import (
    CustomDriveConnection,
)
from metadata.generated.schema.entity.services.connections.testConnectionResult import (
    StatusType,
    TestConnectionResult,
    TestConnectionStepResult,
)
from metadata.ingestion.connections.test_connections import SourceConnectionException
from metadata.ingestion.ometa.ometa_api import OpenMetadata
from metadata.utils.logger import ingestion_logger

logger = ingestion_logger()


def _options(connection: CustomDriveConnection) -> dict:
    if connection.connectionOptions and connection.connectionOptions.root:
        return dict(connection.connectionOptions.root)
    return {}


def _truthy(value: Optional[str], default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def connection_host(connection: CustomDriveConnection) -> str:
    return (_options(connection).get("host") or "").strip()


def connection_port(connection: CustomDriveConnection) -> int:
    raw = _options(connection).get("port") or "21"
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 21


def connection_username(connection: CustomDriveConnection) -> str:
    return (_options(connection).get("username") or "").strip()


def connection_password(connection: CustomDriveConnection) -> str:
    return _options(connection).get("password") or ""


def connection_root_directories(connection: CustomDriveConnection) -> List[str]:
    raw = (_options(connection).get("rootDirectories") or "/").strip()
    if not raw:
        return ["/"]
    # Accept a single path or a comma-separated list.
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    return parts or ["/"]


def connection_extract_sample_data(connection: CustomDriveConnection) -> bool:
    return _truthy(_options(connection).get("extractSampleData"), default=False)


def connection_structured_only(connection: CustomDriveConnection) -> bool:
    return _truthy(_options(connection).get("structuredDataFilesOnly"), default=False)


def connection_passive_mode(connection: CustomDriveConnection) -> bool:
    # ACTIVE_LOCAL disables passive mode; everything else stays passive.
    mode = (_options(connection).get("connectionMode") or "PASSIVE_LOCAL").strip().upper()
    return mode != "ACTIVE_LOCAL"


@dataclass
class FtpAttr:
    """Minimal attribute object compatible with the SFTP listing shape."""

    filename: str
    st_mode: int
    st_size: int = 0
    st_mtime: Optional[float] = None


class FtpSession:
    """Thin FTP wrapper exposing listing and open helpers used by FtpSource."""

    def __init__(self, ftp: FTP):
        self._ftp = ftp

    def close(self) -> None:
        try:
            self._ftp.quit()
        except Exception:
            try:
                self._ftp.close()
            except Exception as exc:
                logger.warning(f"Error closing FTP connection: {exc}")

    def stat(self, path: str = ".") -> None:
        # ftplib has no portable STAT for arbitrary paths; pwd proves access.
        self._ftp.pwd()
        if path not in (".", "", "/"):
            try:
                self._ftp.cwd(path)
                self._ftp.cwd("/")
            except error_perm as exc:
                raise SourceConnectionException(f"Failed to access FTP path '{path}': {exc}") from exc

    def listdir_attr(self, path: str) -> List[FtpAttr]:
        normalized = path.rstrip("/") or "/"
        entries: List[FtpAttr] = []
        try:
            for name, facts in self._ftp.mlsd(normalized):
                if name in (".", ".."):
                    continue
                kind = (facts.get("type") or "").lower()
                is_dir = kind in {"dir", "cdir", "pdir"}
                mode = stat.S_IFDIR if is_dir else stat.S_IFREG
                size = int(facts.get("size") or 0)
                mtime = None
                modify = facts.get("modify")
                if modify and len(modify) >= 14:
                    # YYYYMMDDHHMMSS → approximate unix seconds via calendar fields is enough
                    # for display; keep None when parsing fails.
                    try:
                        from datetime import datetime, timezone

                        mtime = datetime.strptime(modify[:14], "%Y%m%d%H%M%S").replace(
                            tzinfo=timezone.utc
                        ).timestamp()
                    except Exception:
                        mtime = None
                entries.append(FtpAttr(filename=name, st_mode=mode, st_size=size, st_mtime=mtime))
            return entries
        except error_perm:
            # Fall back to NLST when MLSD is unsupported.
            logger.debug(f"MLSD unsupported for '{normalized}', falling back to NLST")
        except Exception as exc:
            logger.debug(f"MLSD failed for '{normalized}': {exc}")

        names = self._ftp.nlst(normalized)
        for full in names:
            name = full.rstrip("/").split("/")[-1]
            if name in (".", ".."):
                continue
            # Heuristic: trailing slash / CWD success means directory.
            is_dir = False
            try:
                candidate = full if full.startswith("/") else f"{normalized.rstrip('/')}/{name}"
                self._ftp.cwd(candidate)
                self._ftp.cwd(normalized if normalized != "/" else "/")
                is_dir = True
            except error_perm:
                is_dir = False
            mode = stat.S_IFDIR if is_dir else stat.S_IFREG
            entries.append(FtpAttr(filename=name, st_mode=mode, st_size=0, st_mtime=None))
        return entries

    def open(self, path: str, mode: str = "r") -> io.BytesIO:
        buffer = io.BytesIO()
        self._ftp.retrbinary(f"RETR {path}", buffer.write)
        buffer.seek(0)
        return buffer


@dataclass
class FtpClient:
    session: FtpSession

    def close(self) -> None:
        self.session.close()


def get_connection(connection: CustomDriveConnection) -> FtpClient:
    host = connection_host(connection)
    username = connection_username(connection)
    password = connection_password(connection)
    if not host or not username:
        raise SourceConnectionException("FTP connection requires host and username")

    ftp = FTP()
    try:
        ftp.connect(host=host, port=connection_port(connection), timeout=30)
        ftp.login(user=username, passwd=password)
        ftp.set_pasv(connection_passive_mode(connection))
        return FtpClient(session=FtpSession(ftp))
    except Exception as exc:
        try:
            ftp.close()
        except Exception:
            pass
        logger.debug(traceback.format_exc())
        raise SourceConnectionException(f"Failed to connect to FTP server: {exc}") from exc


def test_connection(
    metadata: OpenMetadata,
    client: FtpClient,
    service_connection: CustomDriveConnection,
    automation_workflow: Optional[AutomationWorkflow] = None,
) -> TestConnectionResult:
    steps: List[TestConnectionStepResult] = []
    try:
        client.session.stat(".")
        steps.append(
            TestConnectionStepResult(
                name="CheckAccess",
                mandatory=True,
                passed=True,
                message="Connection successful",
            )
        )
    except Exception as exc:
        return TestConnectionResult(
            status=StatusType.Failed,
            steps=[
                TestConnectionStepResult(
                    name="CheckAccess",
                    mandatory=True,
                    passed=False,
                    message=f"Failed to access FTP server: {exc}",
                )
            ],
        )

    try:
        for root in connection_root_directories(service_connection):
            client.session.listdir_attr(root)
        steps.append(
            TestConnectionStepResult(
                name="ListDirectories",
                mandatory=True,
                passed=True,
                message="Directory listing succeeded",
            )
        )
        return TestConnectionResult(status=StatusType.Successful, steps=steps)
    except Exception as exc:
        steps.append(
            TestConnectionStepResult(
                name="ListDirectories",
                mandatory=True,
                passed=False,
                message=f"Failed to list directories: {exc}",
            )
        )
        return TestConnectionResult(status=StatusType.Failed, steps=steps)
