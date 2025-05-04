#!/bin/bash

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL..."
while ! nc -z db 5432; do
  sleep 0.1
done
echo "PostgreSQL started"

# List directory structure for debugging
echo "Current directory: $(pwd)"
echo "Listing directory contents:"
ls -la

# Apply database migrations
echo "Applying database migrations..."
python WebhookMaster/manage.py migrate

# Create superuser if needed
if [ "$CREATE_SUPERUSER" = "true" ]; then
  echo "Creating superuser..."
  python WebhookMaster/manage.py shell -c "
from django.contrib.auth.models import User;
username = '$DJANGO_SUPERUSER_USERNAME';
password = '$DJANGO_SUPERUSER_PASSWORD';
email = '$DJANGO_SUPERUSER_EMAIL';
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, email, password);
    print('Superuser created.');
else:
    print('Superuser already exists.')
  "
fi

# Collect static files
echo "Collecting static files..."
python WebhookMaster/manage.py collectstatic --noinput

# Run the command
if [[ "$*" == *"cd WebhookMaster"* ]]; then
  # If command starts with cd, we need to use bash to execute it
  cd WebhookMaster
  # Remove the "cd WebhookMaster &&" part from the command
  CMD=${@#"cd WebhookMaster && "}
  exec $CMD
else
  # Otherwise, execute as normal
  exec "$@"
fi 