#!/bin/sh
set -eu

# Run from the deployed package root. Azure launches this with: sh startup.sh
cd "$(dirname "$0")"
if [ "${DJANGO_SETTINGS_MODULE:-}" != "config.settings_production" ]; then
    echo "Set DJANGO_SETTINGS_MODULE=config.settings_production before starting." >&2
    exit 1
fi

python manage.py check --deploy --fail-level ERROR
python manage.py collectstatic --noinput
exec python -m gunicorn --config gunicorn.conf.py config.wsgi:application
