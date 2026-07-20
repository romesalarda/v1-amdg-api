#!/bin/sh
# Certbot deploy hook — runs automatically after a successful cert renewal.
#
# Install on EC2:
#   sudo cp scripts/certbot-renewal-hook.sh /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh
#   sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh
#
# Why this is needed:
#   docker-compose.yml bind-mounts individual .pem files from the host into the
#   nginx container. Docker resolves Let's Encrypt symlinks (live/ -> archive/)
#   at container start time. After certbot renews and updates the symlinks to a
#   new archive file, the running container still reads the old file. Sending
#   SIGHUP via `nginx -s reload` causes nginx to re-open its cert files, picking
#   up the new archive paths without a container restart.

set -e

docker exec nginx_server nginx -s reload
