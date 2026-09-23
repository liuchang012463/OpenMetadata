ARG OPENMETADATA_INGESTION_IMAGE=openmetadata/ingestion:1.12.10
FROM ${OPENMETADATA_INGESTION_IMAGE}

USER root
COPY requirements.txt /tmp/om-extension-requirements.txt
RUN python -m pip install --no-cache-dir --no-deps -r /tmp/om-extension-requirements.txt

COPY connectors/ /opt/om-extensions/connectors/
COPY python/ /opt/om-extensions/python/
COPY drivers/ /opt/om-extensions/drivers/

ENV OPENMETADATA_EXTENSION_ROOT=/opt/om-extensions
ENV PYTHONPATH=/opt/om-extensions/python:/opt:/usr/python/lib/python3.10/site-packages:/home/airflow/.local/lib/python3.10/site-packages
ENV PYTHONDONTWRITEBYTECODE=1

RUN chmod -R a+rX /opt/om-extensions
USER airflow
