# OpenMetadata 2.0.4 ingestion extensions

This directory is the source of the Kingbase, Dameng, Vastbase, and FTP
ingestion extensions. It is based on the official OpenMetadata `2.0.4-release`
tag and uses the existing `CustomDatabase` / `CustomDrive` connection types; no
schema fork is needed.

| Connector | Service type | `sourcePythonClass` | Driver |
| --- | --- | --- | --- |
| Kingbase | `CustomDatabase` | `kingbase_connector.kingbase_source.KingbaseSource` | `kingbase8-8.6.0.jar` |
| Dameng | `CustomDatabase` | `dameng_connector.dameng_source.DamengSource` | `DmJdbcDriver8.jar` |
| Vastbase | `CustomDatabase` | `metadata.ingestion.source.database.customdatabase.vastbase_connector.vastbase_source.VastbaseSource` | `Vastbase-G100-2.16_pg_2026062910.jar` |
| FTP | `CustomDrive` | `ftp_connector.ftp_source.FtpSource` | _(stdlib `ftplib`)_ |

Vendor JARs are not committed. Place the three files under
`/mnt/lc/open_metadata_2_0_4/extensions/ingestion-2.0.4/drivers/`, or set
`OPENMETADATA_EXTENSION_DRIVERS` to the directory containing them.

## Prepare the one-directory bind mount

With Docker access to the official base image and the vendor JARs in place:

```bash
OPENMETADATA_INGESTION_IMAGE=docker.getcollate.io/openmetadata/ingestion:2.0.4 \
OPENMETADATA_EXTENSION_DIR=/mnt/lc/open_metadata_2_0_4/extensions/ingestion-2.0.4 \
OPENMETADATA_EXTENSION_DRIVERS=/mnt/lc/open_metadata_2_0_4/extensions/ingestion-2.0.4/drivers \
  ./ingestion/extensions/package-bundle.sh
```

The script stages the source and drivers in that host directory and installs
the pinned `JayDeBeApi`/`JPype1` runtime into it using the base image's Python
  and CPU architecture. This bundle is for Python 3.12. Do not reuse it across Python versions or CPU
architectures.

Mount the bundle read-only in the ingestion service and keep the service's
existing `PYTHONPATH` entries after the extension Python root:

```yaml
image: openmetadata/ingestion:2.0.4-kingbase-dameng-vastbase-custom
environment:
  PYTHONPATH: "/opt/om-extensions/python:/opt"
  PYTHONDONTWRITEBYTECODE: "1"
volumes:
  - /mnt/lc/open_metadata_2_0_4/extensions/ingestion-2.0.4:/opt/om-extensions:ro
```

`sitecustomize.py` adds the top-level connector path, extends the official
`metadata.ingestion.source.database` package path, and sets default driver
paths. Explicit driver environment variables remain supported.

## Optional custom image build

The deployment above does not need a custom image. To build one from this
source tree when an image artifact is preferred:

```bash
OPENMETADATA_EXTENSION_DRIVERS=/mnt/lc/open_metadata_2_0_4/extensions/ingestion-2.0.4/drivers \
OPENMETADATA_IMAGE_TAG=openmetadata/ingestion:2.0.4-kingbase-dameng-vastbase-custom \
  ./ingestion/extensions/build-image.sh
```

The script layers this extension source and the vendor JARs over
`docker.getcollate.io/openmetadata/ingestion:2.0.4`; it builds locally and does not push or deploy.

## FTP (CustomDrive)

OM 2.0.4 has no built-in FTP drive type. The FTP connector mirrors the Kingbase
pattern on the Drive side:

1. SeaTunnel Web creates a `CustomDrive` service with
   `sourcePythonClass=ftp_connector.ftp_source.FtpSource`.
2. Connection fields (`host`, `port`, `username`, `password`, `rootDirectories`,
   `extractSampleData`, `connectionMode`) go into `connectionOptions`.
3. The connector lists directories/files through stdlib `ftplib` and optionally
   extracts CSV/TSV schema + sample rows (same product behaviour as SFTP).

No extra Python dependency or JDBC driver is required for FTP.

## Add another database or drive connector

1. Add its connector package under `connectors/` or
   `python/metadata/ingestion/source/database/customdatabase/`.
2. Implement the source class and a sibling `connection.py` exposing
   `get_connection`; set `sourcePythonClass` to the fully-qualified source class.
3. For databases, add its default driver path in `python/sitecustomize.py` and
   pin new Python dependencies in `requirements.txt`.
4. Add the vendor driver name to the bundle/image checks and this table when a
   JDBC driver is required.
5. Re-run `package-bundle.sh` to update the bind directory. Rebuilding the image
   is optional; restart ingestion only when the running Python process must
   reload an already imported module.
