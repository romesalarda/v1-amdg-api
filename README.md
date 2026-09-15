# AMDG API Platform

Backend service for AMDG

## Tech Stack

- **Framework**: Django 5.1.5 + Django REST Framework
- **Authentication**: Simple JWT (HTTP-only cookies)
- **Real-time**: Django Channels + Redis
- **Background Tasks**: Celery + Redis
- **Database**: PostgreSQL (production) / SQLite (local fallback)
- **Storage**: AWS S3
- **Secrets Management**: AWS SSM Parameter Store
- **Email**: AWS SES (production) / Console (development)
- **Payments**: Stripe
- **API Docs**: drf-spectacular (OpenAPI 3.0)
- **Monitoring**: Sentry (optional)
- **Server**: Uvicorn (ASGI)
- **Proxy**: Nginx with SSL
- **CDN**: Cloudflare

## Prerequisites

- Python 3.10+
- Docker & Docker Compose
- AWS Account (for production)
- PostgreSQL (or use Docker)
- Redis (or use Docker)

## Local Development Setup

### 1. Clone the repository

```bash
git clone https://github.com/romesalarda/v1-amdg-api.git
cd v1-amdg-api
```

### 2. Create environment file

```bash
cp .env.example .env
```

Edit `.env` with your local configuration:
- Set `DEBUG=True`
- Set `USE_POSTGRES=False` to use SQLite (or configure PostgreSQL)
- Configure other variables as needed

### 3. Start with Docker Compose (Recommended)

```bash
# Build and start all services
docker-compose up --build

# Run in detached mode
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

Services will be available at:
- API: http://localhost:8000
- API Docs (Swagger): http://localhost:8000/api/schema/swagger-ui/
- API Docs (ReDoc): http://localhost:8000/api/schema/redoc/
- Admin: http://localhost:8000/admin/

### 4. Alternative: Local Development without Docker

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run development server (Daphne for WebSockets)
daphne -b 0.0.0.0 -p 8000 core.asgi:application

# In another terminal, start Celery worker
celery -A core worker --loglevel=info

# In another terminal, start Celery beat
celery -A core beat --loglevel=info
```

### 5. Create a superuser

```bash
# If using Docker
docker-compose exec web python manage.py createsuperuser

# If running locally
python manage.py createsuperuser
```

## Docker Services

The application runs with the following services:

- **web**: Django application (Uvicorn)
- **db**: PostgreSQL database
- **redis**: Redis for Celery and Channels
- **celery_worker**: Background task worker
- **celery_beat**: Scheduled task dispatcher
- **nginx**: Reverse proxy with SSL

## Configuration

### Environment Variables

See `.env.example` for all available configuration options.

Key variables:

- `SECRET_KEY`: Django secret key
- `DEBUG`: Debug mode (True/False)
- `ALLOWED_HOSTS`: Comma-separated list of allowed hosts
- `USE_SSM`: Use AWS SSM for secrets (True/False)
- `USE_POSTGRES`: Use PostgreSQL (True) or SQLite (False)
- `USE_S3`: Use AWS S3 for static/media files
- `SENTRY_ENABLED`: Enable Sentry monitoring

### AWS SSM Parameter Store (Production)

In production, set `USE_SSM=True` and configure these SSM parameters:

```
/prod/amdg/v1/SECRET_KEY
/prod/amdg/v1/DEBUG
/prod/amdg/v1/ALLOWED_HOSTS
/prod/amdg/v1/DB_ENGINE
/prod/amdg/v1/DB_NAME
/prod/amdg/v1/DB_USER
/prod/amdg/v1/DB_PASSWORD
/prod/amdg/v1/DB_HOST
/prod/amdg/v1/DB_PORT
```

**Important**: SSM reads are batched (max 10 per call) to prevent KMS quota exhaustion.

## Deployment

### GitHub Actions CI/CD

The project includes a complete CI/CD pipeline that:

1. **Builds** Docker images
2. **Tests** the application
3. **Pushes** images to AWS ECR
4. **Deploys** to EC2 via AWS Systems Manager

**Required GitHub Secrets**:

- `AWS_ACCOUNT_ID`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `EC2_INSTANCE_ID`
- `TEST_DB_PASSWORD`

### Manual Deployment to AWS EC2

1. **SSH into EC2 instance**
2. **Clone repository**
3. **Set environment variables** (or configure SSM)
4. **Pull images from ECR**:
   ```bash
   aws ecr get-login-password --region eu-west-2 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.eu-west-2.amazonaws.com
   docker-compose pull
   ```
5. **Start services**:
   ```bash
   docker-compose up -d
   ```
6. **Run migrations**:
   ```bash
   docker-compose exec web python manage.py migrate
   ```

### SSL Certificate Setup (Let's Encrypt)

```bash
# Install certbot
sudo apt-get update
sudo apt-get install certbot

# Obtain certificate
sudo certbot certonly --standalone -d rsalarda.works -d www.rsalarda.works

# Certificates will be at:
# /etc/letsencrypt/live/rsalarda.works/fullchain.pem
# /etc/letsencrypt/live/rsalarda.works/privkey.pem
```

## API Documentation

Access interactive API documentation:

- **Swagger UI**: `/api/schema/swagger-ui/`
- **ReDoc**: `/api/schema/redoc/`
- **OpenAPI Schema**: `/api/schema/`

## Authentication

The API uses JWT tokens with HTTP-only cookies for security.

### Register
```bash
POST /api/auth/register/
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepassword",
  "password_confirm": "securepassword"
}
```

### Login
```bash
POST /api/auth/login/
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepassword"
}
```

Tokens are automatically set as HTTP-only cookies.

### Logout
```bash
POST /api/auth/logout/
Authorization: Bearer <token>
```

## Testing

```bash
# Run tests in Docker
docker-compose exec web python manage.py test

# Run tests locally
python manage.py test

# Run with coverage
coverage run --source='.' manage.py test
coverage report
```

## Custom User Model

The project uses a custom user model (`CommunityUser`) with:

- **Email-based authentication** (not username)
- Username as display field
- OAuth provider support (Google, GitHub)
- Avatar, bio, phone number
- Email verification flag

## WebSockets (Django Channels)

WebSocket support is configured but routes need to be added in:
- `apps/<your_app>/routing.py`
- Update `core/asgi.py` to include your routes

## Email Configuration

**Development**: Emails are printed to console

**Production**: Use AWS SES by setting:
```
EMAIL_BACKEND=django_ses.SESBackend
AWS_SES_REGION_NAME=eu-west-2
```

## Stripe Integration

Configure Stripe in `.env`:
```
STRIPE_TEST_MODE=True
STRIPE_SECRET_KEY_TEST=sk_test_...
STRIPE_PUBLISHABLE_KEY_TEST=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

## Monitoring with Sentry

Enable Sentry by setting:
```
SENTRY_ENABLED=True
SENTRY_DSN=https://...@sentry.io/...
```

## Development Commands

```bash
# Make migrations
python manage.py makemigrations

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Collect static files
python manage.py collectstatic

# Run Django shell
python manage.py shell

# Check for issues
python manage.py check
```

## 📂 Project Structure

```
.
├── core/                   # Django project settings
│   ├── settings.py        # Main settings with SSM support
│   ├── urls.py            # URL routing
│   ├── asgi.py            # ASGI config for Channels
│   ├── wsgi.py            # WSGI config
│   ├── celery.py          # Celery configuration
│   └── storage_backends.py # S3 storage backends
├── apps/
│   └── users/             # User management app
│       ├── models/        # Custom user model
│       ├── api/           # Serializers, viewsets, views
│       └── urls.py        # User endpoints
├── templates/             # Email templates
├── nginx/                 # Nginx configuration
├── .github/workflows/     # CI/CD pipeline
├── Dockerfile             # Docker image definition
├── docker-compose.yml     # Production compose
├── docker-compose.override.yml  # Local development
├── docker-compose.ci.yml  # CI/CD testing
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
└── README.md             # This file
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📄 License

This project is proprietary and confidential.


uvicorn core.asgi:application --reload   

celery -A core worker --loglevel=info  
celery -A core beat --loglevel=info
python manage.py spectacular --file openapi-schema.yml
docker compose --file docker-compose.local.yml up -d

CREATE EXTENSION IF NOT EXISTS pg_trgm;
docker exec -it postgres_db psql -U postgres -d amdg_db -c "SELECT NOW();"
