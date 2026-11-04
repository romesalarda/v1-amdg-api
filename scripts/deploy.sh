#!/usr/bin/env bash
# Build and deploy the currently checked-out revision on the EC2 instance.
#
# Called by .github/workflows/deploy.yaml (via SSM, as root) after the repo has been
# reset to the commit to deploy. Can also be run by hand:
#   cd /home/ec2-user/v1-amdg-api && sudo bash scripts/deploy.sh
#
# Everything that can fail (build, migrate, collectstatic) runs while the old
# containers are still serving traffic; containers are only swapped at the end.
# To roll back: IMAGE_TAG=<previous tag> docker-compose --env-file /run/app.env -f docker-compose.yml up -d
# (`docker images amdg` lists tags; migrations are not reverted).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# safe.directory: this runs as root but the checkout is owned by ec2-user
export IMAGE_TAG="${1:-$(git -c safe.directory="$PWD" rev-parse HEAD)}"
IMAGE_TAG="${IMAGE_TAG:0:12}"
export DOCKER_BUILDKIT=1
# Explicit -f so a docker-compose.override.yml is never picked up on the server.
# --env-file feeds ${VAR} interpolation in the compose file (e.g. DB_PASSWORD for the db service).
COMPOSE="docker-compose --env-file /run/app.env -f docker-compose.yml"

for bin in docker docker-compose aws jq; do
  command -v "$bin" >/dev/null || { echo "ERROR: $bin is not installed" >&2; exit 1; }
done

echo "==> Deploying $IMAGE_TAG"

echo "==> Fetching secrets from SSM"
bash scripts/fetch_secrets.sh
# docker-compose interpolates $ in env_file values; a secret containing one must be written as $$
if grep -q '\$' /run/app.env; then
  echo "WARNING: /run/app.env has values containing a dollar sign (keys below); compose may mangle them:" >&2
  grep '\$' /run/app.env | cut -d= -f1 >&2
fi

# Plain docker build: `docker-compose build` needs a newer buildx plugin than this host has
echo "==> Building image"
docker build -t "amdg:$IMAGE_TAG" .

echo "==> Ensuring db and redis are up"
$COMPOSE up -d db redis

echo "==> Migrating and collecting static files (new image, old containers still live)"
$COMPOSE run --rm -T --no-deps web python manage.py migrate --noinput
$COMPOSE run --rm -T --no-deps web python manage.py collectstatic --noinput

echo "==> Swapping containers"
$COMPOSE up -d --remove-orphans

echo "==> Waiting for django_app to become healthy"
status=missing
for i in $(seq 1 36); do
  status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' django_app 2>/dev/null || echo missing)
  echo "[$i] django_app: $status"
  [ "$status" = "healthy" ] && break
  sleep 5
done
if [ "$status" != "healthy" ]; then
  echo "ERROR: django_app did not become healthy" >&2
  $COMPOSE ps >&2
  $COMPOSE logs --tail=80 web >&2
  exit 1
fi

echo "==> Pruning images/build cache unused for 72h (recent tags are kept for rollback)"
docker image prune -af --filter "until=72h"
docker builder prune -f --filter "until=72h"

$COMPOSE ps
echo "==> Deploy of $IMAGE_TAG complete"
