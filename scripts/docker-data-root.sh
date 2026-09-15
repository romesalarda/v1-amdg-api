#!/bin/bash
# Configure Docker to store all data (images, volumes, containers) on the
# EBS data volume instead of the root volume.
#
# Run ONCE on initial EC2 setup, BEFORE docker-compose up.
# The EBS data volume must already be formatted and mounted at /data.
#
# Usage:
#   sudo bash scripts/docker-data-root.sh
#
# Why:
#   By default Docker writes to /var/lib/docker, which is typically on the
#   root EBS volume (often 8 GB). Named volumes (postgres_data, redis_data)
#   live here too. Redirecting the data-root to a larger EBS volume prevents
#   disk exhaustion from database growth, logs, and pulled images.

set -euo pipefail

DATA_ROOT="/data/docker"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: Must run as root (sudo)." >&2
  exit 1
fi

if ! mountpoint -q /data; then
  echo "ERROR: /data is not a mount point. Mount your EBS data volume at /data first." >&2
  exit 1
fi

if [ -f /etc/docker/daemon.json ]; then
  echo "WARNING: /etc/docker/daemon.json already exists. Inspect it before proceeding."
  cat /etc/docker/daemon.json
  read -r -p "Overwrite? [y/N] " confirm
  [[ "$confirm" =~ ^[Yy]$ ]] || exit 0
fi

mkdir -p "$DATA_ROOT"
mkdir -p /etc/docker

cat > /etc/docker/daemon.json <<EOF
{
  "data-root": "$DATA_ROOT"
}
EOF

echo "Wrote /etc/docker/daemon.json:"
cat /etc/docker/daemon.json
echo ""
echo "Next steps:"
echo "  1. Stop any running containers:  docker compose down"
echo "  2. Stop Docker:                  systemctl stop docker"
echo "  3. Move existing data (optional): rsync -aP /var/lib/docker/ $DATA_ROOT/"
echo "  4. Restart Docker:               systemctl start docker"
echo "  5. Verify data-root:             docker info | grep 'Docker Root Dir'"
