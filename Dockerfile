ARG PYTHON_BASE_IMAGE=python:3.12-slim-bookworm
FROM $PYTHON_BASE_IMAGE AS base

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        curl=7.88.1-10+deb12u14 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.9.21


FROM base AS build

WORKDIR /build

COPY requirements.txt .

RUN uv pip install --system --no-cache-dir -r requirements.txt


FROM dh-mirror.gitverse.ru/hadolint/hadolint:latest-alpine as hadolint

WORKDIR /hadolint

COPY .hadolint.yaml .

COPY Dockerfile .

RUN hadolint Dockerfile


FROM build AS test

WORKDIR /test

# if not set `--from=hadolint` the hadolint stage does not used 
COPY --from=hadolint /hadolint/Dockerfile Dockerfile

COPY src src

RUN uv run ruff check .

# RUN uv run mypy --explicit-package-bases src


FROM base AS runtime

WORKDIR /runtime

COPY requirements.txt .

RUN uv pip install --system --no-cache-dir -r requirements.txt

# if not set `--from=test` the test stage does not used 
COPY --from=test /test/src/main.py src/main.py
COPY pyproject.toml pyproject.toml

EXPOSE 8000

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]