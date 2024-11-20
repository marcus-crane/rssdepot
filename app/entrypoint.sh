#!/usr/bin/env bash

python manage.py migrate
python manage.py collectstatic --no-input --clear

exec "$@"