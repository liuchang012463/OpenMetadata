#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE_IMAGE="${OPENMETADATA_INGESTION_IMAGE:-docker.getcollate.io/openmetadata/ingestion:2.0.4}"
TARGET_DIR="${OPENMETADATA_EXTENSION_DIR:-/mnt/lc/open_metadata_2_0_4/extensions/ingestion-2.0.4}"
DRIVER_DIR="${OPENMETADATA_EXTENSION_DRIVERS:-${TARGET_DIR}/drivers}"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/openmetadata-extension-bundle.XXXXXX")"
trap 'rm -rf -- "${STAGING_DIR}"' EXIT

for driver in kingbase/kingbase8-8.6.0.jar dameng/DmJdbcDriver8.jar vastbase/Vastbase-G100-2.16_pg_2026062910.jar; do
  [[ -f "${DRIVER_DIR}/${driver}" ]] || {
    echo "error: required JDBC driver not found: ${DRIVER_DIR}/${driver}" >&2
    exit 1
  }
done

docker run --rm --entrypoint python "${BASE_IMAGE}" -c \
  'from packaging.version import Version; import sqlalchemy; assert Version(sqlalchemy.__version__) < Version("2.1"), sqlalchemy.__version__'

mkdir -p "${STAGING_DIR}/connectors" "${STAGING_DIR}/python" "${STAGING_DIR}/drivers"
cp -a "${SCRIPT_DIR}/connectors/." "${STAGING_DIR}/connectors/"
cp -a "${SCRIPT_DIR}/python/." "${STAGING_DIR}/python/"
cp -a "${DRIVER_DIR}/." "${STAGING_DIR}/drivers/"

docker run --rm --user "$(id -u):$(id -g)" \
  -v "${STAGING_DIR}/python:/opt/om-extensions/python" \
  -v "${SCRIPT_DIR}/requirements.txt:/tmp/requirements.txt:ro" \
  --entrypoint python "${BASE_IMAGE}" \
  -m pip install --no-cache-dir --no-deps --target /opt/om-extensions/python \
  -r /tmp/requirements.txt

mkdir -p "${TARGET_DIR}"
cp -a "${STAGING_DIR}/." "${TARGET_DIR}/"
chmod -R a+rX "${TARGET_DIR}"

echo "Prepared OpenMetadata extension bundle: ${TARGET_DIR}"
echo "Runtime image: ${BASE_IMAGE}"
