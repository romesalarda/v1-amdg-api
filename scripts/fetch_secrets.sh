#!/usr/bin/env bash
# /opt/app/scripts/fetch_secrets.sh
# Runs once per instance boot (or service start), before uvicorn.
set -euo pipefail

SSM_PREFIX="/prod/amdg/v1/"          # your existing SSM_PARAM_PREFIX
REGION="eu-west-2"
OUT_FILE="/run/app.env"
ENV_FILE="/home/ec2-user/v1-amdg-api/.env"

SECRET_KEYS=(
  SECRET_KEY DEBUG ALLOWED_HOSTS
  DB_ENGINE DB_NAME DB_USER DB_PASSWORD DB_HOST DB_PORT
  AWS_STORAGE_BUCKET_NAME AWS_S3_REGION_NAME
  AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
  STRIPE_TEST_MODE STRIPE_SECRET_KEY_TEST STRIPE_SECRET_KEY_LIVE
  STRIPE_PUBLISHABLE_KEY_TEST STRIPE_PUBLISHABLE_KEY_LIVE STRIPE_WEBHOOK_SECRET
  GOOGLE_OAUTH_CLIENT_ID GOOGLE_OAUTH_CLIENT_SECRET GOOGLE_OAUTH_REDIRECT_URI
)

umask 077   # ensure OUT_FILE is created 600, not world-readable

# Start fresh with the less-critical .env as the base layer
: > "$OUT_FILE"
if [[ -f "$ENV_FILE" ]]; then
  cat "$ENV_FILE" >> "$OUT_FILE"
fi

echo "Fetching ${#SECRET_KEYS[@]} params from SSM..." >&2

# Chunk into groups of 10 (SSM get-parameters limit)
chunk_size=10
for ((i=0; i<${#SECRET_KEYS[@]}; i+=chunk_size)); do
  chunk=("${SECRET_KEYS[@]:i:chunk_size}")
  names=()
  for k in "${chunk[@]}"; do
    names+=("${SSM_PREFIX}${k}")
  done

  result=$(aws ssm get-parameters \
    --region "$REGION" \
    --with-decryption \
    --names "${names[@]}" \
    --output json)

  invalid=$(echo "$result" | jq -r '.InvalidParameters[]?')
  if [[ -n "$invalid" ]]; then
    echo "WARNING: invalid SSM params: $invalid" >&2
  fi

  echo "$result" | jq -r --arg prefix "$SSM_PREFIX" \
    '.Parameters[] | "\(.Name | sub($prefix; ""))=\(.Value)"' >> "$OUT_FILE"
done

chmod 600 "$OUT_FILE"
echo "Secrets written to $OUT_FILE" >&2