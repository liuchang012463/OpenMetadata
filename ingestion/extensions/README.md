# OpenMetadata 1.12.10 database extensions

This directory is the source of the Kingbase, Dameng, and Vastbase ingestion
extensions. It is based on the official OpenMetadata `1.12.10` release branch
and uses its existing `CustomDatabase` connection type; no schema fork is
needed.

| Database | `sourcePythonClass` | Driver |
| --- | --- | --- |
| Kingbase | `kingbase_connector.kingbase_source.KingbaseSource` | `kingbase8-8.6.0.jar` |
| Dameng | `dameng_connector.dameng_source.DamengSource` | `DmJdbcDriver8.jar` |
| Vastbase | `metadata.ingestion.source.database.customdatabase.vastbase_connector.vastbase_source.VastbaseSource` | `Vastbase-G100-2.16_pg_2026062910.jar` |

Vendor JARs are not committed. Place the three files under
`/mnt/lc/open_metadata/extensions/ingestion-1.12.10/drivers/`, or set
`OPENMETADATA_EXTENSION_DRIVERS` to the directory containing them.

## Prepare the one-directory bind mount

With Docker access to the official base image and the vendor JARs in place:

```bash
OPENMETADATA_INGESTION_IMAGE=openmetadata/ingestion:1.12.10 \
OPENMETADATA_EXTENSION_DIR=/mnt/lc/open_metadata/extensions/ingestion-1.12.10 \
OPENMETADATA_EXTENSION_DRIVERS=/mnt/lc/open_metadata/extensions/ingestion-1.12.10/drivers \
  ./ingestion/extensions/package-bundle.sh
```

The script stages the source and drivers in that host directory and installs
the pinned `JayDeBeApi`/`JPype1` runtime into it using the base image's Python
and CPU architecture. Do not reuse the bundle across Python versions or CPU
architectures.

Mount the bundle read-only in the ingestion service and keep the service's
existing `PYTHONPATH` entries after the extension Python root:

```yaml
image: openmetadata/ingestion:1.12.10
environment:
  PYTHONPATH: "/opt/om-extensions/python:/opt:/usr/python/lib/python3.10/site-packages:/home/airflow/.local/lib/python3.10/site-packages"
  PYTHONDONTWRITEBYTECODE: "1"
volumes:
  - /mnt/lc/open_metadata/extensions/ingestion-1.12.10:/opt/om-extensions:ro
```

`sitecustomize.py` adds the top-level connector path, extends the official
`metadata.ingestion.source.database` package path, and sets default driver
paths. Explicit driver environment variables remain supported.

## Optional custom image build

The deployment above does not need a custom image. To build one from this
source tree when an image artifact is preferred:

```bash
OPENMETADATA_EXTENSION_DRIVERS=/mnt/lc/open_metadata/extensions/ingestion-1.12.10/drivers \
OPENMETADATA_IMAGE_TAG=openmetadata/ingestion:1.12.10-kingbase-dameng-vastbase-custom \
  ./ingestion/extensions/build-image.sh
```

The script layers this extension source and the vendor JARs over
`openmetadata/ingestion:1.12.10`; it builds locally and does not push or deploy.

## Add another database

1. Add its connector package under `connectors/` or
   `python/metadata/ingestion/source/database/customdatabase/`.
2. Implement the source class and a sibling `connection.py` exposing
   `get_connection`; set `sourcePythonClass` to the fully-qualified source class.
3. Add its default driver path in `python/sitecustomize.py` and pin new Python
   dependencies in `requirements.txt`.
4. Add the vendor driver name to the bundle/image checks and this table.
5. Re-run `package-bundle.sh` to update the bind directory. Rebuilding the image
   is optional; restart ingestion only when the running Python process must
   reload an already imported module.
