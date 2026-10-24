# Container image for the secrets-rotation CLI/library.
#
# Use cases: running `policy-check` / `audit-report` in CI or as a scheduled
# job, or hosting the API-credential rotation workflow. This image does NOT
# bundle any secret material and runs as a non-root user.
#
# The rotation Lambda is packaged separately (scripts/build_lambda.py); this
# image is for the operator-facing tooling, not the Lambda.

FROM python:3.12-slim AS build

WORKDIR /app
# Copy only what is needed to build the wheel first (better layer caching).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip build \
    && python -m build --wheel --outdir /dist

FROM python:3.12-slim AS runtime

# Create an unprivileged user.
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl \
    && rm -f /tmp/*.whl

# Default policy file location (override by mounting your own).
COPY policies ./policies

USER appuser

# The console script installed by the wheel.
ENTRYPOINT ["secrets-rotation"]
CMD ["--help"]
