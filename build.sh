#!/usr/bin/env bash
# Render runs this file on every deploy (Build Command: bash build.sh).
# Stop at the first error, so a broken build is never put live.
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input

python manage.py migrate --no-input

# Render's free plan has no Shell, so the first admin account is made here.
# It only runs while DJANGO_SUPERUSER_PASSWORD is set in Render's environment
# (together with DJANGO_SUPERUSER_USERNAME and DJANGO_SUPERUSER_EMAIL), and it
# does nothing if that admin already exists. Delete those three variables
# after the first deploy.
if [[ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]]; then
    python manage.py createsuperuser --no-input || true
fi