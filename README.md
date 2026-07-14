# Ethiopia Innovation Hub — Backend

Django + DRF modular monolith. See `docs/` for the full spec.

This repo is fully independent of `innovation-hub-frontend`. Nothing here
requires Node.js or the frontend repo to be checked out.

## Stack

Django 5, DRF, PostgreSQL, JWT auth (`djangorestframework-simplejwt`),
`drf-spectacular`. Local filesystem storage for uploads.

Celery, Redis, and S3 are **not** wired in yet — deferred until you have a
task that actually needs background/scheduled jobs (see
`config/settings/base.py` comments) or need to scale past one API replica
(see `docker-compose.celery-example.yml` for how to bring Celery back, and
switch `STORAGES["default"]` to `storages.backends.s3.S3Storage` — or a
self-hosted MinIO container using the same S3 API — when local disk stops
being enough).

## The contract: `contracts/openapi.yaml`

This file is **generated from the real API**, not hand-written. It is the
one artifact the frontend team consumes — see `contracts/README.md`.

```bash
# After changing any serializer, view, or urls.py:
docker compose exec api ./scripts/export_contract.sh
git add contracts/openapi.yaml
git commit -m "contract: describe what changed"
```

That commit is the "API changed" signal for the frontend team. Push it,
and have them run `npm run sync-contract` in their repo (see their README).

You can also browse the live, always-current schema while `api` is running:
- Raw schema: http://localhost:8000/api/schema/
- Swagger UI: http://localhost:8000/api/schema/swagger-ui/

## First-time setup

```bash
cp .env.example .env
# set a real SECRET_KEY:
python -c "import secrets; print(secrets.token_urlsafe(50))"

docker compose up --build
```

In a second terminal, once containers are healthy:

```bash
docker compose exec api python manage.py migrate
docker compose exec api python manage.py createsuperuser
```

## Repository layout

```
config/            settings/ (base/development/production), urls.py, celery.py
apps/               12 apps — see docs/03-software-design-specification.md Sec 3.2
                    for dependency order. NOTE: docs/05-database-design.md Sec 4.9
                    and 4.10 define a `mentors` app and `payment_transaction` table
                    not listed in Sec 3.2 — resolve before building judging/showcase.
requirements/       base.txt, development.txt, production.txt
contracts/          openapi.yaml — the generated contract (see above)
scripts/            export_contract.sh
docs/               full spec documents (this team's reference copy)
docker-compose.yml  db, api — this team's stack only (Celery/Redis
                    deliberately deferred — see docker-compose.celery-example.yml)
```

## Build order

1. `apps/accounts` first — `AUTH_USER_MODEL = "accounts.Account"` in
   `config/settings/base.py` must be migrated before any other app's
   models, or swapping the user model later is painful.
2. Then in dependency order: `organizations` → `hackathons` →
   `registrations` → `teams` → `submissions` → `judging` → `showcase`.
   `notifications` / `analytics` / `platform_admin` cut across — build them
   alongside whichever app they support first.
3. Every app follows the same four-layer split (`models.py` → `services.py`
   → `serializers.py` → `views.py`) — see docs/03 Sec 3.1.

## Common commands

```bash
docker compose exec api python manage.py makemigrations <app_name>
docker compose exec api pytest
docker compose logs -f api
docker compose down          # keep the db volume
docker compose down -v       # nuke the db volume too
```
