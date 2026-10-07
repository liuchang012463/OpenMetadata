#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE_IMAGE="${OPENMETADATA_INGESTION_IMAGE:-docker.getcollate.io/openmetadata/ingestion:2.0.4}"
IMAGE_TAG="${OPENMETADATA_IMAGE_TAG:-openmetadata/ingestion:2.0.4-kingbase-dameng-vastbase-custom}"
DRIVER_DIR="${OPENMETADATA_EXTENSION_DRIVERS:-/mnt/lc/open_metadata_2_0_4/extensions/ingestion-2.0.4/drivers}"
BUILD_CONTEXT="$(mktemp -d "${TMPDIR:-/tmp}/openmetadata-extension-image.XXXXXX")"
trap 'rm -rf -- "${BUILD_CONTEXT}"' EXIT

for driver in kingbase/kingbase8-8.6.0.jar dameng/DmJdbcDriver8.jar vastbase/Vastbase-G100-2.16_pg_2026062910.jar; do
  [[ -f "${DRIVER_DIR}/${driver}" ]] || {
    echo "error: required JDBC driver not found: ${DRIVER_DIR}/${driver}" >&2
    exit 1
  }
done

cp -a "${SCRIPT_DIR}/connectors" "${SCRIPT_DIR}/python" "${SCRIPT_DIR}/requirements.txt" \
  "${SCRIPT_DIR}/Dockerfile" "${BUILD_CONTEXT}/"
mkdir -p "${BUILD_CONTEXT}/drivers"
cp -a "${DRIVER_DIR}/." "${BUILD_CONTEXT}/drivers/"

docker build \
  --build-arg "OPENMETADATA_INGESTION_IMAGE=${BASE_IMAGE}" \
  --tag "${IMAGE_TAG}" \
  "${BUILD_CONTEXT}"

echo "Built extension image: ${IMAGE_TAG}"
