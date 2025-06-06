FROM python:3.12-alpine AS python-poetry-build-base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VERSION=2.1.1 \
    POETRY_HOME="/opt/poetry" \
    VIRTUAL_ENV="/opt/pysetup/venv" \
    PATH="/opt/pysetup/venv/bin:/opt/poetry/bin:$PATH"

RUN apk add --no-cache --virtual .build-deps \
    curl build-base libffi-dev openssl-dev gcc musl-dev python3-dev openssl \
    && python3 -m venv $VIRTUAL_ENV \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && apk del .build-deps


FROM python-poetry-build-base AS builder-base

WORKDIR /opt/remnashop

COPY pyproject.toml ./

RUN poetry config virtualenvs.create false \
    && poetry config cache-dir false \
    && poetry install --no-root --no-interaction --no-ansi --no-cache

COPY ./app ./app


FROM python-poetry-build-base AS production-builder

WORKDIR /opt/remnashop

COPY --from=builder-base $VIRTUAL_ENV $VIRTUAL_ENV
COPY pyproject.toml README.md ./
COPY ./app ./app

RUN poetry build --no-interaction --no-ansi --no-cache \
    && pip install --no-cache-dir dist/*.whl


FROM python:3.12-alpine AS production

ENV VIRTUAL_ENV="/opt/pysetup/venv"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY --from=production-builder $VIRTUAL_ENV $VIRTUAL_ENV

WORKDIR /opt/remnashop
COPY ./app ./app

ENTRYPOINT ["sh", "-c"]
CMD ["alembic -c app/db/alembic.ini upgrade head && uvicorn app.__main__:app --host 0.0.0.0 --port 5000"]
