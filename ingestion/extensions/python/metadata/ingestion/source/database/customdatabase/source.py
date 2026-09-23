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


"""Dispatch a CustomDatabase source by its sourcePythonClass."""

import importlib
from typing import Optional

from metadata.generated.schema.metadataIngestion.workflow import (
    Source as WorkflowSource,
)
from metadata.ingestion.api.steps import InvalidSourceException, Source
from metadata.ingestion.ometa.ometa_api import OpenMetadata


class CustomDatabaseSource(Source):
    @classmethod
    def create(
        cls,
        config_dict: dict,
        metadata: OpenMetadata,
        pipeline_name: Optional[str] = None,
    ):
        config = WorkflowSource.model_validate(config_dict)
        connection = config.serviceConnection.root.config
        source_python_class = connection.sourcePythonClass
        if not source_python_class:
            raise InvalidSourceException(
                "CustomDatabase connection requires sourcePythonClass"
            )

        module_name, separator, class_name = source_python_class.rpartition(".")
        if not separator:
            raise InvalidSourceException(
                f"Invalid custom source class: {source_python_class}"
            )
        source_class = getattr(importlib.import_module(module_name), class_name)
        return source_class.create(config_dict, metadata, pipeline_name)
