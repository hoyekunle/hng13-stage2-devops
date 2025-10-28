#!/bin/sh
set -eu

# Determine primary and backup hosts based on ACTIVE_POOL
if [ "${ACTIVE_POOL:-blue}" = "green" ]; then
  PRIMARY_HOST=app_green
  BACKUP_HOST=app_blue
else
  PRIMARY_HOST=app_blue
  BACKUP_HOST=app_green
fi

# Create nginx.conf from template by substituting placeholders
if [ -f /etc/nginx/nginx.conf.template ]; then
  sed "s/\${PRIMARY_HOST}/$PRIMARY_HOST/g; s/\${BACKUP_HOST}/$BACKUP_HOST/g" /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf
else
  echo "ERROR: /etc/nginx/nginx.conf.template not found"
  exit 1
fi

# Start nginx in foreground
exec nginx -g 'daemon off;'
