ARG OPENMETADATA_INGESTION_IMAGE=docker.getcollate.io/openmetadata/ingestion:2.0.4
FROM ${OPENMETADATA_INGESTION_IMAGE}

USER root
COPY requirements.txt /tmp/om-extension-requirements.txt
RUN python -m pip install --no-cache-dir --no-deps -r /tmp/om-extension-requirements.txt
RUN python -c 'from packaging.version import Version; import sqlalchemy; assert Version(sqlalchemy.__version__) < Version("2.1"), sqlalchemy.__version__'

COPY connectors/ /opt/om-extensions/connectors/
COPY python/ /opt/om-extensions/python/
COPY drivers/ /opt/om-extensions/drivers/

ENV OPENMETADATA_EXTENSION_ROOT=/opt/om-extensions
ENV PYTHONPATH=/opt/om-extensions/python:/opt
ENV PYTHONDONTWRITEBYTECODE=1

RUN chmod -R a+rX /opt/om-extensions
USER airflow
