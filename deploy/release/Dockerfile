# syntax=docker/dockerfile:1.7
# A sealed PREDICTIVE delivery (v4 Phase 5): the value compiled to native, the
# glue to bytecode, no readable .py, and a signed integrity manifest checked at
# startup. Build with deploy/release/build.sh.
ARG PYTHON=python:3.12-slim

FROM ${PYTHON} AS builder
ENV PYTHONDONTWRITEBYTECODE=0 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential patchelf ccache libpq-dev libffi-dev \
    libheif1 libde265-0 libpango-1.0-0 libpangoft2-1.0-0 libcairo2 exiftool \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml .
RUN pip install -e ".[dev]" && pip install nuitka
COPY . .
ARG COMPILE_LIMIT=
# Close the source: value to native, glue to bytecode, strip the .py.
RUN python deploy/release/compile.py --report /app/compile-report.json \
    ${COMPILE_LIMIT:+--limit ${COMPILE_LIMIT}}
# The delivery is the program only. Tests (they spell out the rules) and the
# dev/test settings (dev.py reads LICENSE_PUBLIC_KEY and MACHINE_ID_FILE from
# the environment: shipped, it would let anyone bypass the licence) move to
# the verify stage, before signing so the manifest never lists them.
RUN mkdir -p /verify/settings && mv tests /verify/tests \
    && mv config/settings/dev.pyc config/settings/test.pyc /verify/settings/ \
    && rm -rf deploy scripts .github
# Sign the integrity manifest with the signing key, mounted as a secret so it
# never lands in a layer.
RUN --mount=type=secret,id=signing_key --mount=type=secret,id=signing_pw \
    DJANGO_SETTINGS_MODULE=config.settings.prod SECRET_KEY=build-only ALLOWED_HOSTS=build \
    python manage.py license sign-manifest \
      --signing-key /run/secrets/signing_key --password-file /run/secrets/signing_pw

FROM ${PYTHON} AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DJANGO_SETTINGS_MODULE=config.settings.prod
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 libffi8 libheif1 libde265-0 libpango-1.0-0 libpangoft2-1.0-0 libcairo2 exiftool \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app
ARG BUILD_TENANT=""
ARG BUILD_VERSION=""
ARG BUILD_ID=""
ENV BUILD_TENANT=${BUILD_TENANT} BUILD_VERSION=${BUILD_VERSION} BUILD_ID=${BUILD_ID}
# A system user with no login: it runs PREDICTIVE and writes its data, and
# cannot touch the program, which stays root-owned.
RUN useradd --system --create-home --home-dir /home/predictive --shell /usr/sbin/nologin predictive \
    && mkdir -p /app/data && chown predictive:predictive /app/data
USER predictive
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]

# Never delivered: the delivery image plus its tests, so the suite runs on the
# compiled program exactly as shipped (AC-5.2).
FROM runtime AS verify
COPY --from=builder /verify/tests /app/tests
COPY --from=builder /verify/settings/ /app/config/settings/
ENV DJANGO_SETTINGS_MODULE=config.settings.test
