# AMDG API — Infrastructure & Deployment Guide

> **Who this is for**: Someone who has just cloned this repository for the first time and needs to get it running, either locally or on AWS. No prior experience assumed beyond basic terminal usage.

---

## Table of Contents

1. [What This Project Is](#1-what-this-project-is)
2. [Architecture Overview](#2-architecture-overview)
3. [Local Development Setup](#3-local-development-setup)
   - [Option A — Docker (Recommended)](#option-a--docker-recommended)
   - [Option B — No Docker](#option-b--no-docker)
4. [Environment Variables Explained](#4-environment-variables-explained)
5. [AWS Account Setup (One-Time)](#5-aws-account-setup-one-time)
   - [IAM — Permissions](#51-iam--permissions)
   - [SSM — Secrets Management](#52-ssm--secrets-management)
   - [ECR — Container Registry](#53-ecr--container-registry)
   - [S3 — File Storage](#54-s3--file-storage)
   - [SES — Email Sending](#55-ses--email-sending)
6. [Provisioning a New EC2 Instance](#6-provisioning-a-new-ec2-instance)
7. [SSL / TLS Certificates](#7-ssl--tls-certificates)
8. [Cloudflare DNS Setup](#8-cloudflare-dns-setup)
9. [CSRF & Security Settings](#9-csrf--security-settings)
10. [CI/CD Pipeline (GitHub Actions)](#10-cicd-pipeline-github-actions)
11. [Manual Deployment](#11-manual-deployment)
12. [Post-Deployment Checklist](#12-post-deployment-checklist)
13. [Common Commands Reference](#13-common-commands-reference)
14. [Fast Start-Up Reminders (Returning to EC2)](#14-fast-start-up-reminders-returning-to-ec2)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. What This Project Is

This is the backend API for **AMDG Events**, a Django REST Framework application that handles events, bookings, attendees, payments (Stripe), and real-time updates (WebSockets).

**Live URLs:**
- API: `https://api.amdgevents.co.uk`
- Top-level site: `https://amdgevents.co.uk`

**Tech stack at a glance:**

| Layer | Technology |
|---|---|
| Framework | Django 5.1.5 + Django REST Framework |
| Authentication | JWT via HTTP-only cookies |
| Real-time | Django Channels (WebSockets) |
| Background tasks | Celery |
| Message broker | Redis (used by both Celery and Channels) |
| Database | PostgreSQL 16 |
| File/static storage | AWS S3 |
| Secrets | AWS SSM Parameter Store |
| Email | AWS SES (production) / Mailpit (local dev) |
| Payments | Stripe |
| Server | Uvicorn (ASGI — handles both HTTP and WebSockets) |
| Reverse proxy | Nginx |
| CDN + DNS | Cloudflare |

---

## 2. Architecture Overview

```
Browser / Client
      |
      v
Cloudflare (DNS, CDN, DDoS protection, SSL to browser)
      |
      v  HTTPS port 443
Nginx (reverse proxy running in Docker on EC2)
      |            |
      |            +-- /ws/* -> WebSocket upgrade -> Uvicorn
      v
Uvicorn (ASGI server -- handles HTTP + WebSockets in one process)
      |
      v
Django Application
      |               |
      v               v
PostgreSQL 16      Redis 7
(all app data)     (Celery task queue + Django Channels layer)
                       |
               +-------+-------+
               v               v
         Celery Worker    Celery Beat
         (runs async      (triggers
          tasks e.g.       scheduled
          emails, jobs)    tasks on a timer)
```

**Docker containers** (defined in `docker-compose.yml`):

| Container name | What it does |
|---|---|
| `django_app` | The Django/Uvicorn server (HTTP + WebSockets) |
| `celery_worker` | Picks up and processes background tasks |
| `celery_beat` | Triggers scheduled/periodic tasks |
| `postgres_db` | The database |
| `redis_server` | Message broker and Channels layer |
| `nginx_server` | Sits in front of Django, handles SSL termination |

> In **production** the Django image is always **pulled from AWS ECR** — it is never built on the EC2 instance itself.
> In **local dev** (`docker-compose.local.yml`) the image is built from the `Dockerfile` in this repo.

---

## 3. Local Development Setup

### Prerequisites

Before anything else, install these on your machine:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)
- [Python 3.10+](https://www.python.org/downloads/) (only needed for Option B)
- [Git](https://git-scm.com/downloads/)

### Clone the repository

```bash
git clone https://github.com/romesalarda/v1-amdg-api.git
cd v1-amdg-api
```

### Create your local .env file

The app reads configuration from a `.env` file. An example with all available options is provided:

```bash
# Windows (PowerShell)
Copy-Item .env.example .env

# macOS / Linux
cp .env.example .env
```

Now open `.env` in a text editor. For local development the defaults are mostly fine, but check:

- `DEBUG=True` — leave this as `True` locally
- `USE_POSTGRES=True` — uses PostgreSQL (the Docker compose will start it for you)
- `USE_S3=False` — files are stored locally, no AWS needed
- `USE_SSM=False` — secrets come from the `.env` file, not AWS
- `DB_PASSWORD=changeme` — change this to anything you like for local use
- `SECRET_KEY=` — paste any long random string here (it is only your local machine)

---

### Option A — Docker (Recommended)

This spins up all services (Django, PostgreSQL, Redis, Celery, Mailpit) in containers.
You do not need Python or PostgreSQL installed locally.

**First run** (or any time you change Python dependencies or the `Dockerfile`):

```powershell
# PowerShell
$env:COMPOSE_BAKE="false"; docker compose -f docker-compose.local.yml up --build
```

```bash
# macOS / Linux
COMPOSE_BAKE=false docker compose -f docker-compose.local.yml up --build
```

**Subsequent runs** (no code changes that affect the image):

```bash
docker compose -f docker-compose.local.yml up -d
```

The `-d` flag runs everything in the background (detached mode).

**Shut everything down**:

```bash
docker compose -f docker-compose.local.yml down

# To also wipe the database (useful for a clean slate):
docker compose -f docker-compose.local.yml down -v
```

**Apply database migrations** (first time, and whenever you add new models):

```bash
docker compose -f docker-compose.local.yml exec web python manage.py migrate
```

**Create your admin user**:

```bash
docker compose -f docker-compose.local.yml exec web python manage.py createsuperuser
```

**Local URLs once running:**

| What | URL |
|---|---|
| API root | http://localhost:8000 |
| Swagger UI (interactive API docs) | http://localhost:8000/api/schema/swagger-ui/ |
| ReDoc API docs | http://localhost:8000/api/schema/redoc/ |
| Django Admin | http://localhost:8000/admin/ |
| Mailpit (catch all outgoing emails) | http://localhost:8025 |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |

> **Mailpit** intercepts every outgoing email — nothing actually gets sent. Open http://localhost:8025 to read them.

---

### Option B — No Docker

Use this if Docker is not available or you want faster iteration without containers.
You will need PostgreSQL and Redis installed and running on your machine separately (or use the `docker-compose.local.yml` just for those services).

```bash
# Create a virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# Install all Python dependencies
pip install -r requirements.txt
```

Update your `.env` so Django can find your local services:

```
DB_HOST=localhost
REDIS_HOST=localhost
CELERY_BROKER_URL=redis://localhost:6379/1
CHANNEL_LAYERS_HOST=localhost:6379
```

```bash
# Apply database migrations
python manage.py migrate

# Create your admin user
python manage.py createsuperuser

# Start the development server (ASGI -- required for WebSocket support)
uvicorn core.asgi:application --reload
```

Open **two more terminals** (with the venv activated) for the background task workers:

```bash
# Terminal 2 -- Celery worker
# Windows requires --pool=solo (no multiprocessing support)
celery -A core worker --loglevel=info --pool=solo

# macOS / Linux
celery -A core worker --loglevel=info
```

```bash
# Terminal 3 -- Celery beat (scheduled tasks)
celery -A core beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

---

## 4. Environment Variables Explained

All configuration lives in `.env` (local) or AWS SSM (production). See `.env.example` for the full list.

| Variable | What it does | Local value | Production value |
|---|---|---|---|
| `SECRET_KEY` | Django cryptographic key -- keep this secret | Any random string | Long random string from SSM |
| `DEBUG` | Shows detailed error pages | `True` | `False` |
| `ALLOWED_HOSTS` | Domains Django will respond to | `localhost,127.0.0.1,web` | `api.amdgevents.co.uk` |
| `USE_SSM` | Load config from AWS SSM instead of .env | `False` | `True` |
| `SSM_PARAM_PREFIX` | AWS SSM path prefix | -- | `/prod/amdg/v1/` |
| `USE_POSTGRES` | Use PostgreSQL (vs SQLite fallback) | `True` | `True` |
| `DB_HOST` | Database hostname | `db` (Docker) / `localhost` | `db` |
| `DB_PASSWORD` | Database password | Anything | SSM SecureString |
| `USE_S3` | Upload files to AWS S3 | `False` | `True` |
| `REDIS_HOST` | Redis hostname | `redis` (Docker) / `localhost` | `redis` |
| `CELERY_BROKER_URL` | Where Celery sends tasks | `redis://redis:6379/1` | `redis://redis:6379/1` |
| `CHANNEL_LAYERS_HOST` | Redis address for WebSockets | `redis:6379` | `redis:6379` |
| `EMAIL_BACKEND` | How emails are sent | console or Mailpit SMTP | `django_ses.SESBackend` |
| `STRIPE_TEST_MODE` | Use Stripe test keys | `True` | `False` |
| `SENTRY_ENABLED` | Send errors to Sentry | `False` | `True` |
| `CORS_ALLOWED_ORIGINS` | Allowed frontend origins | `http://localhost:3000` | `https://amdgevents.co.uk` |
| `CSRF_TRUSTED_ORIGINS` | Trusted origins for CSRF | `http://localhost:3000` | `https://api.amdgevents.co.uk` |

---

## 5. AWS Account Setup (One-Time)

This section only needs to be done once per AWS account. Skip it if AWS is already set up.

### 5.1 IAM -- Permissions

You need two separate IAM things:

**A) EC2 Instance Role** (gives the EC2 server permission to talk to AWS services)

1. Go to **AWS Console -> IAM -> Roles -> Create role**
2. Select **AWS service -> EC2**
3. Name it something like `amdg-ec2-role`
4. Attach the managed policy **`AmazonSSMManagedInstanceCore`** -- required for SSM remote commands and reading parameters
5. Add an **inline policy** with this JSON (replace `<ACCOUNT_ID>` and `<YOUR_BUCKET_NAME>`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath"
      ],
      "Resource": "arn:aws:ssm:eu-west-2:<ACCOUNT_ID>:parameter/prod/amdg/v1/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetAuthorizationToken"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["ses:SendEmail", "ses:SendRawEmail"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::<YOUR_BUCKET_NAME>",
        "arn:aws:s3:::<YOUR_BUCKET_NAME>/*"
      ]
    }
  ]
}
```

6. After creating the role, go to your EC2 instance -> **Actions -> Security -> Modify IAM role** -> select `amdg-ec2-role`

**B) GitHub Actions IAM User** (gives the CI/CD pipeline permission to push images and deploy)

1. Go to **IAM -> Users -> Create user**
2. Name it `amdg-github-actions`
3. Select **Attach policies directly** and add an inline policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssm:SendCommand",
        "ssm:ListCommands",
        "ssm:ListCommandInvocations",
        "ssm:GetCommandInvocation",
        "ssm:DescribeInstanceInformation",
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceStatus"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ],
      "Resource": "*"
    }
  ]
}
```

4. Go to the user -> **Security credentials -> Create access key** -> select **Application running outside AWS**
5. Copy the `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` -- you will add these as GitHub Secrets (see [Section 10](#10-cicd-pipeline-github-actions))

---

### 5.2 SSM -- Secrets Management

In production, Django loads all config from AWS SSM Parameter Store instead of a `.env` file. This keeps secrets off disk and out of the repository.

**Create each parameter:**

Go to **AWS Console -> Systems Manager -> Parameter Store -> Create parameter**

- Name: `/prod/amdg/v1/SECRET_KEY`
- Tier: Standard
- Type: **SecureString** for sensitive values, **String** for everything else
- Value: the actual value

Required parameters:

```
# Core Django
/prod/amdg/v1/SECRET_KEY              <- SecureString
/prod/amdg/v1/DEBUG                   = False
/prod/amdg/v1/ALLOWED_HOSTS           = api.amdgevents.co.uk
/prod/amdg/v1/ENVIRONMENT             = production

# Database
/prod/amdg/v1/USE_POSTGRES            = True
/prod/amdg/v1/DB_ENGINE               = django.db.backends.postgresql
/prod/amdg/v1/DB_NAME                 = amdg_db
/prod/amdg/v1/DB_USER                 = postgres
/prod/amdg/v1/DB_PASSWORD             <- SecureString
/prod/amdg/v1/DB_HOST                 = db
/prod/amdg/v1/DB_PORT                 = 5432

# Redis / Celery
/prod/amdg/v1/REDIS_HOST              = redis
/prod/amdg/v1/REDIS_PORT              = 6379
/prod/amdg/v1/CELERY_BROKER_URL       = redis://redis:6379/1
/prod/amdg/v1/CHANNEL_LAYERS_HOST     = redis:6379

# AWS Storage
/prod/amdg/v1/USE_S3                  = True
/prod/amdg/v1/AWS_STORAGE_BUCKET_NAME = your-bucket-name
/prod/amdg/v1/AWS_S3_REGION_NAME      = eu-west-2

# Email (SES)
/prod/amdg/v1/EMAIL_BACKEND           = django_ses.SESBackend
/prod/amdg/v1/AWS_SES_REGION_NAME     = eu-west-2
/prod/amdg/v1/DEFAULT_FROM_EMAIL      = noreply@amdgevents.co.uk

# CORS / CSRF
/prod/amdg/v1/CORS_ALLOWED_ORIGINS    = https://amdgevents.co.uk
/prod/amdg/v1/CORS_ALLOW_ALL_ORIGINS  = False
/prod/amdg/v1/CSRF_TRUSTED_ORIGINS    = https://api.amdgevents.co.uk,https://amdgevents.co.uk

# JWT
/prod/amdg/v1/JWT_ACCESS_TOKEN_LIFETIME_MINUTES  = 15
/prod/amdg/v1/JWT_REFRESH_TOKEN_LIFETIME_DAYS    = 7

# Stripe
/prod/amdg/v1/STRIPE_TEST_MODE        = False
/prod/amdg/v1/STRIPE_SECRET_KEY       <- SecureString
/prod/amdg/v1/STRIPE_PUBLISHABLE_KEY  <- SecureString
/prod/amdg/v1/STRIPE_WEBHOOK_SECRET   <- SecureString

# Sentry
/prod/amdg/v1/SENTRY_ENABLED          = True
/prod/amdg/v1/SENTRY_DSN              <- SecureString
```

> **Note**: SSM reads are batched in groups of 10 to avoid KMS rate limits. This is handled automatically.

Or create them via the AWS CLI:

```bash
aws ssm put-parameter \
  --name "/prod/amdg/v1/SECRET_KEY" \
  --value "your-actual-secret-key" \
  --type "SecureString" \
  --region eu-west-2
```

---

### 5.3 ECR -- Container Registry

ECR (Elastic Container Registry) stores the built Docker image. The CI/CD pipeline pushes to it; the EC2 instance pulls from it.

**Create the repository** (one-time):

```bash
aws ecr create-repository \
  --repository-name amdg \
  --region eu-west-2
```

Note the URI it returns -- it looks like:
```
123456789012.dkr.ecr.eu-west-2.amazonaws.com/amdg
```
The `123456789012` part is your AWS account ID. You will need this as the `AWS_ACCOUNT_ID` GitHub Secret.

---

### 5.4 S3 -- File Storage

S3 stores user-uploaded media files and can host static files.

1. Go to **S3 -> Create bucket**
2. Region: `eu-west-2`
3. Name it (e.g. `amdg-media-prod`) -- must be globally unique
4. Leave **Block all public access** enabled (Django signs URLs, direct public access is not needed)
5. Add the bucket name to SSM as `/prod/amdg/v1/AWS_STORAGE_BUCKET_NAME`

---

### 5.5 SES -- Email Sending

SES sends transactional emails (booking confirmations, password resets, etc.).

1. Go to **SES -> Verified identities -> Create identity**
2. Choose **Domain** and enter `amdgevents.co.uk`
3. Add the DKIM DNS records it gives you to Cloudflare
4. If your account is still in SES **sandbox mode**, you can only send to verified addresses. Request production access via **SES -> Account dashboard -> Request production access**

---

## 6. Provisioning a New EC2 Instance

Do this once to set up a brand new server. Everything here assumes **Amazon Linux 2023**.

### 6.1 Launch the instance (AWS Console)

1. Go to **EC2 -> Launch instance**
2. Choose **Amazon Linux 2023 AMI**
3. Instance type: `t3.small` or larger (Celery + Redis + Postgres + Django needs memory)
4. Key pair: create one and download the `.pem` file -- **you cannot download it again after this**
5. Security group -- open these ports:
   - **22** (SSH) from your IP only
   - **80** (HTTP) from anywhere (Cloudflare will hit this during cert renewal)
   - **443** (HTTPS) from anywhere
6. Storage: at least **20 GB**
7. Under **Advanced details -> IAM instance profile**: select `amdg-ec2-role`
8. Launch

### 6.2 Connect via SSH

```bash
# Fix key file permissions (required on macOS / Linux -- AWS will reject the key otherwise)
chmod 400 ~/path/to/your-key.pem

# Connect (replace with your EC2 public IP)
ssh -i ~/path/to/your-key.pem ec2-user@<YOUR_EC2_PUBLIC_IP>
```

> On **Windows**, use PuTTY or Windows Terminal. In Windows Terminal / PowerShell the `chmod` command is not needed but ensure the `.pem` file is only readable by your user account.

### 6.3 Install Docker

```bash
# Update all system packages first
sudo dnf update -y

# Install Docker
sudo dnf install -y docker

# Start Docker immediately
sudo systemctl start docker

# Make Docker start automatically every time the instance boots
sudo systemctl enable docker

# Allow ec2-user to run Docker without sudo every time
sudo usermod -aG docker ec2-user

# Apply the group change to your current SSH session (avoids needing to log out and back in)
newgrp docker

# Confirm Docker is working
docker --version
```

### 6.4 Install Docker Compose v2.17.0

The project uses the standalone `docker-compose` binary. Pin it to **v2.17.0** for reproducibility:

```bash
sudo curl -L \
  "https://github.com/docker/compose/releases/download/v2.17.0/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose

# Make it executable
sudo chmod +x /usr/local/bin/docker-compose

# Verify
docker-compose --version
# Expected: Docker Compose version v2.17.0
```

### 6.5 Install Git and clone the repository

```bash
sudo dnf install -y git

# Create a deploy SSH key so the instance can pull from GitHub
ssh-keygen -t ed25519 -C "ec2-amdg-deploy"
# Press Enter for all prompts (leave passphrase blank for a server deploy key)

# Print the public key -- copy this output
cat ~/.ssh/id_ed25519.pub
```

Go to **GitHub -> repository -> Settings -> Deploy keys -> Add deploy key**, paste the public key, tick **read-only**, and save.

```bash
# Clone the repository into /home/ec2-user/app
git clone git@github.com:romesalarda/v1-amdg-api.git /home/ec2-user/app
cd /home/ec2-user/app
```

### 6.6 Set bootstrap environment variables

Django needs two variables before it can read everything else from SSM. Set them now and persist them across reboots:

```bash
sudo tee -a /etc/environment <<EOF
USE_SSM=True
SSM_PARAM_PREFIX=/prod/amdg/v1/
AWS_REGION=eu-west-2
ECR_REGISTRY=<YOUR_ACCOUNT_ID>.dkr.ecr.eu-west-2.amazonaws.com
IMAGE_TAG=latest
EOF

# Load them into the current session
source /etc/environment
```

> Do **not** create a `.env` file on the EC2 instance for production. The `docker-compose.yml` file has no `env_file` directive intentionally -- all secrets come from SSM only.

### 6.7 Log in to ECR and pull the image

```bash
aws ecr get-login-password --region eu-west-2 \
  | docker login --username AWS --password-stdin \
    ${ECR_REGISTRY}
```

> This token expires after 12 hours. The CI/CD pipeline re-authenticates automatically on every deploy.

### 6.8 Start the application for the first time

```bash
cd /home/ec2-user/app

# Download all images from ECR
docker-compose pull

# Start all containers in the background
docker-compose up -d

# Watch the startup logs (Ctrl+C to stop watching, containers keep running)
docker-compose logs -f
```

Wait until all containers show as healthy:

```bash
docker-compose ps
```

Expected output:

```
NAME              STATUS
django_app        Up (healthy)
celery_worker     Up (healthy)
celery_beat       Up
postgres_db       Up (healthy)
redis_server      Up (healthy)
nginx_server      Up
```

---

## 7. SSL / TLS Certificates

Nginx needs a certificate to serve HTTPS. We use **Let's Encrypt** for the certificate between Cloudflare and EC2.

> Do this **after** Cloudflare DNS is pointing to your EC2 IP (see [Section 8](#8-cloudflare-dns-setup)) and **before** starting Nginx. Certbot needs port 80 free, so stop Nginx first.

### Stop Nginx

```bash
docker-compose stop nginx_server
```

### Install certbot on Amazon Linux 2023

```bash
sudo dnf install -y python3-pip
sudo pip3 install certbot
```

### Obtain the certificate

```bash
sudo certbot certonly --standalone \
  -d api.amdgevents.co.uk
```

Certbot will ask for your email address and to agree to the terms. On success, certificates are written to:

```
/etc/letsencrypt/live/api.amdgevents.co.uk/fullchain.pem
/etc/letsencrypt/live/api.amdgevents.co.uk/privkey.pem
```

### Update nginx.conf

The `nginx/nginx.conf` file currently references the old domain. Update these two lines:

```nginx
# Change this:
server_name rsalarda.works www.rsalarda.works;

# To this:
server_name api.amdgevents.co.uk;
```

```nginx
# Change these:
ssl_certificate /etc/letsencrypt/live/rsalarda.works/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/rsalarda.works/privkey.pem;

# To these:
ssl_certificate /etc/letsencrypt/live/api.amdgevents.co.uk/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/api.amdgevents.co.uk/privkey.pem;
```

Also update the volume mounts in `docker-compose.yml` to match the new certificate paths.

### Start Nginx

```bash
docker-compose up -d nginx_server
```

Open `https://api.amdgevents.co.uk` -- you should see a valid certificate.

### Auto-renewal

Let's Encrypt certificates expire every 90 days. Add a cron job:

```bash
sudo tee /etc/cron.d/certbot-renew <<'EOF'
0 0 * * * root certbot renew --quiet \
  --pre-hook "docker-compose -f /home/ec2-user/app/docker-compose.yml stop nginx_server" \
  --post-hook "docker-compose -f /home/ec2-user/app/docker-compose.yml start nginx_server"
EOF

sudo chmod 644 /etc/cron.d/certbot-renew
```

---

## 8. Cloudflare DNS Setup

Cloudflare handles DNS, DDoS protection, caching, and provides the public-facing SSL certificate to browsers.

> **SSL Mode**: Set this to **Full (Strict)** in Cloudflare (**SSL/TLS -> Overview**). This validates the Let's Encrypt certificate on your EC2 origin -- the most secure option.

### DNS records to add

Go to **Cloudflare -> amdgevents.co.uk -> DNS -> Add record**:

| Type | Name | Content | Proxied |
|---|---|---|---|
| `A` | `api` | `<YOUR_EC2_PUBLIC_IP>` | Yes (orange cloud) |
| `A` | `@` | `<YOUR_EC2_PUBLIC_IP>` | Yes (orange cloud) |

The `api` record makes `api.amdgevents.co.uk` resolve to your EC2 instance.

### Important: Elastic IP

Every time an EC2 instance is **stopped and restarted**, AWS gives it a new public IP address. You would then need to update Cloudflare's DNS record manually each time.

**Fix this permanently** with an Elastic IP:

1. Go to **EC2 -> Elastic IPs -> Allocate Elastic IP address** -> Allocate
2. Select the new Elastic IP -> **Actions -> Associate Elastic IP address** -> choose your instance
3. Use this IP in Cloudflare -- it stays the same even after restarts

> There is a small charge (~$0.005/hour) if the Elastic IP is allocated while the instance is **stopped**. It is free while the instance is running.

---

## 9. CSRF & Security Settings

Django checks which domains are allowed to submit requests. These are configured via SSM in production:

```
/prod/amdg/v1/CSRF_TRUSTED_ORIGINS  = https://api.amdgevents.co.uk,https://amdgevents.co.uk
/prod/amdg/v1/CORS_ALLOWED_ORIGINS  = https://amdgevents.co.uk
```

The following security settings activate automatically in `core/settings.py` when `DEBUG=False`:

```python
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')  # Trust Cloudflare's forwarded header
SECURE_SSL_REDIRECT = True        # Redirect plain HTTP to HTTPS
SESSION_COOKIE_SECURE = True      # Only send session cookie over HTTPS
CSRF_COOKIE_SECURE = True         # Only send CSRF cookie over HTTPS
```

These are already in the codebase -- no changes needed.

---

## 10. CI/CD Pipeline (GitHub Actions)

When you push to `main`, GitHub automatically builds, tests, and deploys to EC2. No manual SSH required.

### Workflows

| File | Triggered by | What it does |
|---|---|---|
| `.github/workflows/deploy.yaml` | Push or PR to `main` | Build, test, push to ECR, deploy to EC2 |
| `.github/workflows/staging.yaml` | Push or PR to `staging` | Build and test only (no deploy) |

### What happens when you push to `main`

```
1.  Build Docker image from the Dockerfile in this repo
2.  Start test environment with docker-compose.ci.yml (PostgreSQL + Redis)
3.  Wait for database and Redis health checks to pass
4.  Run: python manage.py migrate
5.  Run: python manage.py test
6.  Tear down test containers
7.  If tests pass: build the production image and push to ECR with two tags:
      <account>.dkr.ecr.eu-west-2.amazonaws.com/amdg:<git-sha>   (exact version)
      <account>.dkr.ecr.eu-west-2.amazonaws.com/amdg:latest       (latest)
8.  Send a remote command to EC2 via AWS SSM:
      - aws ecr get-login-password | docker login
      - docker-compose pull              (download the new image from ECR)
      - docker-compose down              (stop running containers)
      - docker-compose up -d             (start with the new image)
      - python manage.py migrate         (apply any new database migrations)
      - python manage.py collectstatic   (sync static files to S3)
      - docker image prune -af           (remove old images to free disk)
```

### Required GitHub Secrets

Go to **GitHub -> repository -> Settings -> Secrets and variables -> Actions -> New repository secret**:

| Secret name | What it is | Where to get it |
|---|---|---|
| `AWS_ACCOUNT_ID` | 12-digit AWS account number | AWS Console top-right, click your name |
| `AWS_ACCESS_KEY_ID` | CI/CD IAM user access key | Created in Section 5.1 |
| `AWS_SECRET_ACCESS_KEY` | CI/CD IAM user secret key | Created in Section 5.1 |
| `EC2_INSTANCE_ID` | The EC2 instance ID | EC2 Console -> your instance, looks like `i-0abc1234...` |
| `TEST_DB_PASSWORD` | Password for the throwaway CI test database | Any string, e.g. `ci-test-password` |

> After **replacing an EC2 instance**, update `EC2_INSTANCE_ID` in GitHub Secrets.

---

## 11. Manual Deployment

Use this when you need to deploy without pushing to `main` (e.g. emergency hotfix, or after updating SSM parameters).

```bash
# SSH in
ssh -i ~/path/to/your-key.pem ec2-user@<EC2_IP>

# Go to app directory
cd /home/ec2-user/app

# Ensure environment variables are set
source /etc/environment

# Authenticate with ECR
aws ecr get-login-password --region eu-west-2 \
  | docker login --username AWS --password-stdin ${ECR_REGISTRY}

# Pull the latest image
docker-compose pull

# Restart everything
docker-compose down
docker-compose up -d

# Apply any pending database migrations
docker-compose exec -T web python manage.py migrate --noinput

# Sync static files to S3
docker-compose exec -T web python manage.py collectstatic --noinput

# Confirm everything is healthy
docker-compose ps
```

---

## 12. Post-Deployment Checklist

After first-time setup or any major deployment:

- [ ] `docker-compose ps` -- all containers show `Up (healthy)` or `Up`
- [ ] Migrations applied: `docker-compose exec web python manage.py migrate --noinput`
- [ ] Static files collected: `docker-compose exec web python manage.py collectstatic --noinput`
- [ ] Superuser created: `docker-compose exec -it web python manage.py createsuperuser`
- [ ] HTTPS working: visit `https://api.amdgevents.co.uk/api/health/` in a browser
- [ ] SSL padlock shows -- Cloudflare Full Strict mode is working
- [ ] Cloudflare DNS `A` record for `api` points to the correct IP
- [ ] Celery worker logs look healthy: `docker-compose logs celery_worker --tail=20`
- [ ] Celery beat logs look healthy: `docker-compose logs celery_beat --tail=20`
- [ ] Send a test email and check it arrives (or review SES send logs)
- [ ] Stripe webhook endpoint set to `https://api.amdgevents.co.uk/api/payments/webhook/` in Stripe Dashboard
- [ ] Stripe webhook secret in SSM matches the one shown in Stripe Dashboard
- [ ] Sentry is receiving events if `SENTRY_ENABLED=True`
- [ ] `pg_trgm` extension enabled (required for text search features):
  ```bash
  docker exec -it postgres_db psql -U postgres -d amdg_db \
    -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
  ```

---

## 13. Common Commands Reference

### Viewing logs

```bash
# Follow all service logs at once
docker-compose logs -f

# Follow a specific service
docker-compose logs -f web
docker-compose logs -f celery_worker
docker-compose logs -f nginx_server

# Show last 50 lines without following
docker-compose logs --tail=50 web
```

### Entering a container

```bash
# Get a bash shell inside the Django container
docker-compose exec -it web bash

# Open Django's interactive Python shell (useful for querying the database manually)
docker-compose exec web python manage.py shell
```

### Database

```bash
# Open PostgreSQL command line
docker exec -it postgres_db psql -U postgres -d amdg_db

# Quick sanity check
docker exec -it postgres_db psql -U postgres -d amdg_db -c "SELECT NOW();"

# Enable pg_trgm extension (run once after first migration)
docker exec -it postgres_db psql -U postgres -d amdg_db \
  -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

### Redis

```bash
# Ping Redis (should print PONG)
docker-compose exec redis redis-cli ping

# Watch all Redis commands in real-time (useful for debugging Celery or Channels)
docker-compose exec redis redis-cli monitor
```

### Django management commands

```bash
# Create new migration files after changing a model
docker-compose exec web python manage.py makemigrations

# Apply pending migrations
docker-compose exec web python manage.py migrate

# Create a superuser (admin access)
docker-compose exec web python manage.py createsuperuser

# Collect static files to S3
docker-compose exec web python manage.py collectstatic --noinput

# Check for configuration errors
docker-compose exec web python manage.py check

# Generate the OpenAPI schema file (used by the frontend client generator)
docker-compose exec web python manage.py spectacular --file openapi-schema.yml
```

### Celery

```bash
# Check workers are alive and connected
docker-compose exec celery_worker celery -A core inspect ping

# See tasks currently being processed
docker-compose exec celery_worker celery -A core inspect active

# List all registered task names
docker-compose exec celery_worker celery -A core inspect registered
```

### Restart a single service

```bash
docker-compose restart celery_worker
docker-compose restart web
```

### Free up disk space

Docker images from old deployments accumulate. Run this periodically:

```bash
docker image prune -af
```

---

## 14. Fast Start-Up Reminders (Returning to EC2)

If the EC2 instance was stopped and you are starting it again:

1. **Update Cloudflare DNS** -- If you do not have an Elastic IP, the public IP will have changed. Update the `A` record for `api.amdgevents.co.uk` in Cloudflare.

2. **Check GitHub Secrets** -- If the instance was replaced (not just stopped/started), update `EC2_INSTANCE_ID` in GitHub Secrets.

3. **SSH in and bring services up:**

```bash
ssh -i ~/path/to/your-key.pem ec2-user@<EC2_PUBLIC_IP>
cd /home/ec2-user/app

# Bootstrap variables are persisted in /etc/environment
# Load them if they are not already in your session
source /etc/environment

# Start all containers
docker-compose up -d
```

4. **Verify everything is healthy:**

```bash
docker-compose ps
```

---

## 15. Troubleshooting

### Containers won't start or keep restarting

```bash
# Check which containers are failing
docker-compose ps

# Read the startup error for that container
docker-compose logs web
docker-compose logs db
docker-compose logs celery_worker
```

### Django cannot connect to PostgreSQL

- Inside Docker, the database hostname is `db` not `localhost`. Ensure `DB_HOST=db` (or that SSM has `DB_HOST=db`).
- The `web` container waits for `db` to pass its health check. If `db` stays unhealthy, check `docker-compose logs db`.
- Verify `DB_USER` and `DB_PASSWORD` match in both the `db` service environment and Django settings.

### Redis connection refused

```bash
docker-compose exec redis redis-cli ping
```

- Inside Docker, Redis is at `redis:6379`. Check `REDIS_HOST=redis`, `CELERY_BROKER_URL=redis://redis:6379/1`, and `CHANNEL_LAYERS_HOST=redis:6379`.
- For non-Docker local dev change all three to use `localhost`.

### WebSocket connections fail

- Nginx passes WebSocket requests at `/ws/*` to Uvicorn. This is configured in `nginx/nginx.conf` and should work out of the box.
- The server must use the ASGI entrypoint (`core.asgi:application`), not the WSGI one. Confirm the `web` container command contains `core.asgi:application`.
- Check `CHANNEL_LAYERS_HOST` points to the Redis instance.

### Celery tasks never run

```bash
docker-compose exec celery_worker celery -A core inspect ping
```

- If this hangs or errors, the worker cannot reach Redis. Check `CELERY_BROKER_URL`.
- Check `docker-compose logs celery_worker` for Python import errors or missing environment variables.

### Emails not sending in production

- Confirm `EMAIL_BACKEND=django_ses.SESBackend` is set in SSM.
- Check the SES domain `amdgevents.co.uk` is verified (DKIM records added to Cloudflare DNS).
- Check the EC2 instance role includes `ses:SendEmail` permission.
- If SES is still in sandbox mode, only verified addresses can receive email. Request production access in the SES console.
- In **local dev**, all emails go to **Mailpit** at http://localhost:8025 -- nothing leaves your machine.

### SSM parameters not loading

- `USE_SSM=True` must be in the environment before Django starts. Check `/etc/environment` on the EC2 instance.
- Check the EC2 instance role has `ssm:GetParametersByPath` on `arn:aws:ssm:eu-west-2:<ACCOUNT_ID>:parameter/prod/amdg/v1/*`.
- Parameter names are **case-sensitive** -- check they match exactly.

### CI/CD deploy step fails or hangs

- Confirm `EC2_INSTANCE_ID` in GitHub Secrets matches the current running instance.
- Ensure the instance is **running** (not stopped) when a deploy triggers.
- Check `AmazonSSMManagedInstanceCore` is attached to the instance IAM role.
- Check the SSM agent is running on the instance:
  ```bash
  sudo systemctl status amazon-ssm-agent
  ```
  If stopped:
  ```bash
  sudo systemctl start amazon-ssm-agent
  sudo systemctl enable amazon-ssm-agent
  ```

### Disk space running low

```bash
# Remove all unused images (safe to run at any time)
docker image prune -af

# More aggressive: remove everything not currently in use
docker system prune -f
```

### SSL certificate expired / HTTPS broken

```bash
# Renew the certificate manually
sudo certbot renew

# Reload Nginx to pick up the new certificate
docker-compose exec nginx_server nginx -s reload
```
