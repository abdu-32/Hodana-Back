# One image for api / worker / beat — Doc 08 Sec 2.3: "beat reuses the
# api/worker image with a different entrypoint rather than a fourth image,
# to minimize build surface." docker-compose.yml sets the CMD per service.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

ARG REQUIREMENTS_FILE=requirements/production.txt
COPY requirements/ ./requirements/
RUN pip install -r ${REQUIREMENTS_FILE}

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "python manage.py collectstatic --noinput && python manage.py migrate && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 3"]

