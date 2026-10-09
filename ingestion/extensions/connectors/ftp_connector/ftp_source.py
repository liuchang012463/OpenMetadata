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

"""FTP Drive source loaded through OpenMetadata CustomDrive + sourcePythonClass."""

from __future__ import annotations

import io
import mimetypes
import stat
import traceback
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from metadata.generated.schema.api.data.createDirectory import CreateDirectoryRequest
from metadata.generated.schema.api.data.createFile import CreateFileRequest
from metadata.generated.schema.api.data.createSpreadsheet import CreateSpreadsheetRequest
from metadata.generated.schema.api.data.createWorksheet import CreateWorksheetRequest
from metadata.generated.schema.entity.data.directory import Directory, DirectoryType
from metadata.generated.schema.entity.data.file import File, FileType
from metadata.generated.schema.entity.data.table import Column, DataType, TableData
from metadata.generated.schema.entity.services.connections.drive.customDriveConnection import (
    CustomDriveConnection,
)
from metadata.generated.schema.entity.services.driveService import DriveService
from metadata.generated.schema.entity.services.ingestionPipelines.status import (
    StackTraceError,
)
from metadata.generated.schema.metadataIngestion.driveServiceMetadataPipeline import (
    DriveServiceMetadataPipeline,
)
from metadata.generated.schema.metadataIngestion.workflow import (
    Source as WorkflowSource,
)
from metadata.ingestion.api.models import Either
from metadata.ingestion.api.steps import InvalidSourceException
from metadata.ingestion.ometa.ometa_api import OpenMetadata
from metadata.ingestion.source.drive.drive_service import DriveServiceSource
from metadata.utils import fqn
from metadata.utils.filters import filter_by_directory, filter_by_file
from metadata.utils.logger import ingestion_logger

from ftp_connector.connection import (
    FtpClient,
    connection_extract_sample_data,
    connection_root_directories,
    connection_structured_only,
)
from ftp_connector.connection import get_connection  # noqa: F401
from ftp_connector.connection import test_connection  # noqa: F401

# get_connection / test_connection are re-exported for OpenMetadata's
# custom-connector importer (resolved from the sourcePythonClass module).

logger = ingestion_logger()

CSV_EXTENSIONS = {".csv", ".tsv"}
STRUCTURED_DATA_EXTENSIONS = {".csv", ".tsv", ".json", ".jsonl", ".parquet", ".avro"}
MAX_SAMPLE_ROWS = 50
CHUNKSIZE = 200

PANDAS_DTYPE_MAP = {
    "int64": DataType.INT,
    "int32": DataType.INT,
    "float64": DataType.FLOAT,
    "float32": DataType.FLOAT,
    "bool": DataType.BOOLEAN,
    "datetime64[ns]": DataType.DATETIME,
    "object": DataType.STRING,
}


class FtpDirectoryInfo:
    def __init__(
        self,
        name: str,
        full_path: str,
        parents: Optional[List[str]] = None,
        path: Optional[List[str]] = None,
        modified_time: Optional[float] = None,
    ):
        self.name = name
        self.full_path = full_path
        self.parents = parents or []
        self.path = path
        self.modified_time = modified_time


class FtpFileInfo:
    def __init__(
        self,
        name: str,
        full_path: str,
        size: Optional[int] = None,
        modified_time: Optional[float] = None,
        mime_type: Optional[str] = None,
    ):
        self.name = name
        self.full_path = full_path
        self.size = size
        self.modified_time = modified_time
        self.mime_type = mime_type


class FtpSource(DriveServiceSource):
    """CustomDrive FTP source aligned with the official SFTP drive topology."""

    def __init__(self, config: WorkflowSource, metadata: OpenMetadata):
        super().__init__()
        self.config = config
        self.source_config: DriveServiceMetadataPipeline = self.config.sourceConfig.config
        self.metadata = metadata
        self.service_connection: CustomDriveConnection = self.config.serviceConnection.root.config
        self.client: FtpClient = get_connection(self.service_connection)
        self.connection_obj = self.client
        self._connection = None

        self._directories_cache: Dict[str, FtpDirectoryInfo] = {}
        self._files_by_parent_cache: Dict[str, List[FtpFileInfo]] = {}
        self._directory_fqn_cache: Dict[str, str] = {}
        self._current_directory_context: Optional[str] = None
        self._root_files_processed: bool = False
        self._root_directory_prefixes: List[str] = []
        self._extract_sample_data = connection_extract_sample_data(self.service_connection)
        self._structured_only = connection_structured_only(self.service_connection)

    @classmethod
    def create(
        cls,
        config_dict,
        metadata: OpenMetadata,
        pipeline_name: Optional[str] = None,
    ):
        config: WorkflowSource = WorkflowSource.model_validate(config_dict)
        connection = config.serviceConnection.root.config
        if not isinstance(connection, CustomDriveConnection):
            raise InvalidSourceException(
                f"Expected CustomDriveConnection, but got {connection}"
            )
        return cls(config, metadata)

    def _build_directory_path(self, full_path: str) -> List[str]:
        clean_path = full_path.strip("/")
        if not clean_path:
            return []
        components = clean_path.split("/")
        for root_prefix in self._root_directory_prefixes:
            prefix_parts = root_prefix.strip("/").split("/")
            if components[: len(prefix_parts)] == prefix_parts:
                components = components[len(prefix_parts) :]
                break
        return components

    def _get_full_path_for_stripped(self, stripped_path: Optional[List[str]]) -> Optional[str]:
        if not stripped_path:
            return None
        stripped_path_str = "/" + "/".join(stripped_path)
        if stripped_path_str in self._directories_cache:
            return stripped_path_str
        for root_prefix in self._root_directory_prefixes:
            full_path = root_prefix.rstrip("/") + "/" + "/".join(stripped_path)
            if full_path in self._directories_cache:
                return full_path
        return None

    def _fetch_directories(self) -> None:
        try:
            root_dirs = connection_root_directories(self.service_connection)
            self._root_directory_prefixes = [d.rstrip("/") for d in root_dirs if d != "/"]
            directories: Dict[str, FtpDirectoryInfo] = {}
            for root_dir in root_dirs:
                self._fetch_directories_recursive(root_dir, directories)
            self._directories_cache = directories
            self._fetch_all_files()
        except Exception as exc:
            logger.error(f"Error fetching FTP directories: {exc}")
            logger.debug(traceback.format_exc())

    def _fetch_directories_recursive(
        self,
        path: str,
        directories: Dict[str, FtpDirectoryInfo],
        parent_path: Optional[str] = None,
    ) -> None:
        try:
            normalized_path = path.rstrip("/") or "/"
            entries = self.client.session.listdir_attr(normalized_path)
            for entry in entries:
                if not stat.S_ISDIR(entry.st_mode):
                    continue
                dir_name = entry.filename
                full_path = f"/{dir_name}" if normalized_path == "/" else f"{normalized_path}/{dir_name}"
                path_components = self._build_directory_path(full_path)
                parent_paths = path_components[:-1] if len(path_components) > 1 else []
                directories[full_path] = FtpDirectoryInfo(
                    name=dir_name,
                    full_path=full_path,
                    parents=parent_paths,
                    modified_time=entry.st_mtime,
                    path=path_components,
                )
                self._fetch_directories_recursive(full_path, directories, full_path)
        except Exception as exc:
            logger.warning(f"Error fetching FTP directories from {path}: {exc}")
            logger.debug(traceback.format_exc())

    def _fetch_all_files(self) -> None:
        try:
            files_by_parent: Dict[str, List[FtpFileInfo]] = {}
            total_files = 0
            for full_path in list(self._directories_cache.keys()):
                try:
                    for entry in self.client.session.listdir_attr(full_path):
                        if stat.S_ISDIR(entry.st_mode):
                            continue
                        total_files += 1
                        file_path = (
                            f"/{entry.filename}"
                            if full_path == "/"
                            else f"{full_path}/{entry.filename}"
                        )
                        mime_type, _ = mimetypes.guess_type(entry.filename)
                        files_by_parent.setdefault(full_path, []).append(
                            FtpFileInfo(
                                name=entry.filename,
                                full_path=file_path,
                                size=entry.st_size,
                                modified_time=entry.st_mtime,
                                mime_type=mime_type,
                            )
                        )
                except Exception as exc:
                    logger.warning(f"Error fetching FTP files from {full_path}: {exc}")

            for root_dir in connection_root_directories(self.service_connection):
                try:
                    normalized_root = root_dir.rstrip("/") or "/"
                    for entry in self.client.session.listdir_attr(normalized_root):
                        if stat.S_ISDIR(entry.st_mode):
                            continue
                        total_files += 1
                        file_path = (
                            f"/{entry.filename}"
                            if normalized_root == "/"
                            else f"{normalized_root}/{entry.filename}"
                        )
                        mime_type, _ = mimetypes.guess_type(entry.filename)
                        files_by_parent.setdefault("root", []).append(
                            FtpFileInfo(
                                name=entry.filename,
                                full_path=file_path,
                                size=entry.st_size,
                                modified_time=entry.st_mtime,
                                mime_type=mime_type,
                            )
                        )
                except Exception as exc:
                    logger.warning(f"Error fetching FTP root files from {root_dir}: {exc}")

            self._files_by_parent_cache = files_by_parent
            logger.debug(f"Cached {total_files} FTP files across {len(files_by_parent)} directories")
        except Exception as exc:
            logger.error(f"Error fetching FTP files: {exc}")
            logger.debug(traceback.format_exc())
            self._files_by_parent_cache = {}

    def _ensure_root_file_directory(self) -> None:
        """Register a catalog directory for flat roots that only contain files.

        OpenMetadata's drive topology only runs {@code yield_file} as a child of
        {@code get_directory_names}. When the configured root has files but no
        child directories, nothing would be produced. Mirror those files under a
        synthetic directory named after the root path so both schema and sample
        extraction still run.
        """
        root_files = self._files_by_parent_cache.get("root") or []
        if not root_files:
            return
        for root_dir in connection_root_directories(self.service_connection):
            full_path = root_dir.rstrip("/") or "/"
            if full_path in self._directories_cache:
                # Real child directories already exist; keep root files on the
                # dedicated "root" key that yield_file drains first.
                continue
            name = full_path.rstrip("/").split("/")[-1] or "root"
            self._directories_cache[full_path] = FtpDirectoryInfo(
                name=name,
                full_path=full_path,
                parents=[],
                path=[name],
            )
            # Attach the flat root files to this directory so they are emitted
            # as children of a real CreateDirectoryRequest.
            self._files_by_parent_cache[full_path] = list(root_files)
        # Avoid double-emitting once the synthetic directory owns the files.
        self._files_by_parent_cache.pop("root", None)

    def _sort_directories_by_hierarchy(self) -> List[str]:
        children_map: Dict[str, List[str]] = {}
        root_directories = []
        for full_path, directory_info in self._directories_cache.items():
            parent_stripped_path = directory_info.path[:-1] if directory_info.path and len(directory_info.path) > 1 else None
            parent_full_path = (
                self._get_full_path_for_stripped(parent_stripped_path) if parent_stripped_path else None
            )
            if parent_full_path is None or parent_full_path not in self._directories_cache:
                root_directories.append(full_path)
            else:
                children_map.setdefault(parent_full_path, []).append(full_path)

        ordered_directories: List[str] = []
        visited = set()

        def dfs(directory_path: str):
            if directory_path in visited:
                return
            visited.add(directory_path)
            ordered_directories.append(directory_path)
            for child_path in children_map.get(directory_path, []):
                dfs(child_path)

        for root_path in root_directories:
            dfs(root_path)
        for dir_path in self._directories_cache:
            if dir_path not in visited:
                ordered_directories.append(dir_path)
        return ordered_directories

    def get_directory_names(self) -> Iterable[str]:
        try:
            if not self.source_config.includeDirectories:
                return
            self._fetch_directories()
            self._ensure_root_file_directory()
            ordered_directory_paths = self._sort_directories_by_hierarchy()
            included_directories = set()
            for dir_path in ordered_directory_paths:
                directory_info = self._directories_cache[dir_path]
                should_include = True
                if directory_info.parents:
                    parent_full_path = self._get_full_path_for_stripped(directory_info.parents)
                    if (
                        parent_full_path
                        and parent_full_path in self._directories_cache
                        and parent_full_path not in included_directories
                    ):
                        should_include = False
                if not should_include:
                    continue
                directory_fqn = fqn.build(
                    self.metadata,
                    entity_type=Directory,
                    service_name=self.context.get().drive_service,
                    directory_path=[directory_info.name],
                )
                if not filter_by_directory(
                    self.source_config.directoryFilterPattern,
                    (directory_fqn if self.source_config.useFqnForFiltering else directory_info.name),
                ):
                    included_directories.add(dir_path)
                    yield dir_path
        except Exception as exc:
            logger.error(f"Error getting FTP directory names: {exc}")
            logger.debug(traceback.format_exc())

    def get_file_names(self) -> Iterable[str]:
        return iter([])

    def yield_directory(self, directory_path: str) -> Iterable[Either[CreateDirectoryRequest]]:
        if not self.source_config.includeDirectories:
            return
        try:
            directory_info = self._directories_cache.get(directory_path)
            if not directory_info:
                return
            self._current_directory_context = directory_path
            parent_reference = None
            if directory_info.parents:
                parent_full_path = self._get_full_path_for_stripped(directory_info.parents)
                if parent_full_path and parent_full_path in self._directories_cache:
                    parent_info = self._directories_cache[parent_full_path]
                    parent_reference = fqn.build(
                        self.metadata,
                        entity_type=Directory,
                        service_name=self.context.get().drive_service,
                        directory_path=parent_info.path or [parent_info.name],
                    )
            service_fqn = fqn.build(
                self.metadata,
                entity_type=DriveService,
                service_name=self.context.get().drive_service,
            )
            request = CreateDirectoryRequest(
                name=directory_info.name,
                directoryType=DirectoryType.Folder,
                displayName=directory_info.name,
                service=service_fqn,
                parent=parent_reference,
                path=(".".join(directory_info.path) if directory_info.path else directory_info.name),
            )
            path_components = directory_info.path or [directory_info.name]
            self._directory_fqn_cache[directory_path] = fqn.build(
                self.metadata,
                entity_type=Directory,
                service_name=self.context.get().drive_service,
                directory_path=path_components,
            )
            self.register_record_directory(request)
            yield Either(right=request)
        except Exception as exc:
            logger.error(f"Error creating FTP directory request for {directory_path}: {exc}")
            yield Either(
                left=StackTraceError(
                    name=directory_path,
                    error=f"Error creating directory {directory_path}: {exc}",
                    stackTrace=traceback.format_exc(),
                )
            )

    def register_record_directory(self, directory_request: CreateDirectoryRequest) -> None:
        if self._current_directory_context and self._current_directory_context in self._directories_cache:
            directory_info = self._directories_cache[self._current_directory_context]
            path_components = directory_info.path or [directory_info.name]
            directory_fqn = fqn.build(
                self.metadata,
                entity_type=Directory,
                service_name=self.context.get().drive_service,
                directory_path=path_components,
            )
        else:
            directory_fqn = fqn.build(
                self.metadata,
                entity_type=Directory,
                service_name=self.context.get().drive_service,
                directory_path=[directory_request.name.root],
            )
        self.directory_source_state.add(directory_fqn)

    def register_record_file(
        self,
        file_request: CreateFileRequest,
        directory_path: Optional[List[str]] = None,
    ) -> None:
        service_name = self.context.get().drive_service
        if directory_path:
            file_fqn = fqn.build(
                self.metadata,
                entity_type=File,
                service_name=service_name,
                directory_path=directory_path,
                file_name=file_request.name.root,
            )
        else:
            file_fqn = fqn._build(service_name, file_request.name.root)
        self.file_source_state.add(file_fqn)

    def yield_file(self, directory_path: str) -> Iterable[Either[CreateFileRequest]]:
        if not getattr(self.source_config, "includeFiles", True):
            return
        try:
            service_fqn = fqn.build(
                self.metadata,
                entity_type=DriveService,
                service_name=self.context.get().drive_service,
            )
            if not self._root_files_processed:
                for file_info in self._files_by_parent_cache.get("root", []):
                    yield from self._yield_one_file(
                        file_info, service_fqn, directory_reference=None, directory_path_components=None
                    )
                self._root_files_processed = True

            if directory_path == "root":
                return

            files_in_directory = self._files_by_parent_cache.get(directory_path, [])
            if not files_in_directory:
                return

            directory_reference = self._directory_fqn_cache.get(directory_path)
            directory_path_components = None
            if directory_path in self._directories_cache:
                directory_info = self._directories_cache[directory_path]
                directory_path_components = directory_info.path or [directory_info.name]

            for file_info in files_in_directory:
                yield from self._yield_one_file(
                    file_info,
                    service_fqn,
                    directory_reference=directory_reference,
                    directory_path_components=directory_path_components,
                )
        except Exception as exc:
            logger.error(f"Error processing FTP files in directory {directory_path}: {exc}")
            yield Either(
                left=StackTraceError(
                    name=directory_path,
                    error=f"Error processing directory files: {exc}",
                    stackTrace=traceback.format_exc(),
                )
            )

    def _yield_one_file(
        self,
        file_info: FtpFileInfo,
        service_fqn: str,
        directory_reference: Optional[str],
        directory_path_components: Optional[List[str]],
    ) -> Iterable[Either[CreateFileRequest]]:
        try:
            if filter_by_file(self.source_config.fileFilterPattern, file_info.name):
                return
            if self._structured_only and not self._is_structured_data_file(file_info.name):
                return

            columns = None
            sample_data = None
            file_type = None
            if self._is_csv_file(file_info.name):
                file_type = FileType.CSV
                columns, sample_data = self._extract_csv_schema(
                    file_info.full_path,
                    file_info.name,
                    extract_sample_data=self._extract_sample_data,
                )

            request = CreateFileRequest(
                name=file_info.name,
                displayName=file_info.name,
                service=service_fqn,
                directory=directory_reference,
                mimeType=file_info.mime_type,
                size=file_info.size,
                fileType=file_type,
                columns=columns,
            )
            self.register_record_file(request, directory_path=directory_path_components)
            yield Either(right=request)
            if sample_data:
                self._ingest_sample_data_for_file(
                    file_name=file_info.name,
                    directory_path=directory_path_components,
                    sample_data=sample_data,
                )
        except Exception as file_exc:
            logger.error(f"Error processing FTP file {file_info.name}: {file_exc}")
            yield Either(
                left=StackTraceError(
                    name=file_info.name,
                    error=f"Error creating file {file_info.name}: {file_exc}",
                    stackTrace=traceback.format_exc(),
                )
            )

    def get_spreadsheets_list(self) -> Any:
        return []

    def get_spreadsheet_name(self, spreadsheet: Any) -> str:
        return ""

    def get_spreadsheet_details(self, spreadsheet: Any) -> Any:
        return None

    def yield_spreadsheet(self, spreadsheet_details: Any) -> Iterable[Either[CreateSpreadsheetRequest]]:
        return iter([])

    def yield_worksheet(self, spreadsheet_details: Any) -> Iterable[Either[CreateWorksheetRequest]]:
        return iter([])

    def close(self) -> None:
        try:
            self._directories_cache.clear()
            self._current_directory_context = None
            self._files_by_parent_cache.clear()
            self._directory_fqn_cache.clear()
            self._root_files_processed = False
            if self.client is not None:
                self.client.close()
        except Exception as exc:
            logger.error(f"Error closing FTP source: {exc}")
            logger.debug(traceback.format_exc())

    def _is_csv_file(self, filename: str) -> bool:
        lower_name = filename.lower()
        return any(lower_name.endswith(ext) for ext in CSV_EXTENSIONS)

    def _is_structured_data_file(self, filename: str) -> bool:
        lower_name = filename.lower()
        return any(lower_name.endswith(ext) for ext in STRUCTURED_DATA_EXTENSIONS)

    def _ingest_sample_data_for_file(
        self,
        file_name: str,
        directory_path: Optional[List[str]],
        sample_data: TableData,
    ) -> None:
        try:
            if not directory_path:
                directory_path = [self.context.get().drive_service]
            file_fqn = fqn.build(
                self.metadata,
                entity_type=File,
                service_name=self.context.get().drive_service,
                directory_path=directory_path,
                file_name=file_name,
            )
            file_entity = self.metadata.get_by_name(entity=File, fqn=file_fqn)
            if file_entity:
                self.metadata.ingest_file_sample_data(file_entity, sample_data)
            else:
                logger.warning(f"Could not find file entity to ingest sample data: {file_fqn}")
        except Exception as exc:
            logger.error(f"Failed to ingest sample data for FTP file {file_name}: {exc}")
            logger.debug(traceback.format_exc())

    def _get_csv_separator(self, filename: str) -> str:
        if filename.lower().endswith(".tsv"):
            return "\t"
        return ","

    def _extract_csv_schema(
        self, file_path: str, filename: str, extract_sample_data: bool = False
    ) -> tuple[Optional[List[Column]], Optional[TableData]]:
        try:
            separator = self._get_csv_separator(filename)
            with self.client.session.open(file_path, "r") as remote_file:
                content = remote_file.read()
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="ignore")
            df = pd.read_csv(
                io.StringIO(content),
                sep=separator,
                nrows=CHUNKSIZE,
                encoding_errors="ignore",
            )
            if len(df.columns) == 0:
                return None, None
            columns = []
            for col_name in df.columns:
                dtype_str = str(df[col_name].dtype)
                data_type = PANDAS_DTYPE_MAP.get(dtype_str, DataType.STRING)
                columns.append(
                    Column(
                        name=str(col_name),
                        displayName=str(col_name),
                        dataType=data_type,
                        dataTypeDisplay=data_type.value,
                    )
                )
            sample_data = None
            if extract_sample_data:
                sample_df = df.head(MAX_SAMPLE_ROWS)
                sample_rows = [
                    [str(val) if pd.notna(val) else None for val in row]
                    for _, row in sample_df.iterrows()
                ]
                sample_data = TableData(
                    columns=[str(col) for col in df.columns],
                    rows=sample_rows,
                )
            return columns, sample_data
        except Exception as exc:
            logger.error(f"Failed to extract FTP CSV schema from {file_path}: {exc}")
            logger.debug(traceback.format_exc())
            return None, None
