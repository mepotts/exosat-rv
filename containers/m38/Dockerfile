# The digest is duplicated in runtime-contract.json so the static audit binds it.
FROM python:3.11-slim@sha256:233de06753d30d120b1a3ce359d8d3be8bda78524cd8f520c99883bfe33964cf

COPY --chown=65532:65532 runtime-contract.json /opt/m38/runtime-contract.json
COPY --chown=65532:65532 entrypoint.py /opt/m38/entrypoint.py

USER 65532:65532
ENTRYPOINT ["python", "-I", "/opt/m38/entrypoint.py"]
