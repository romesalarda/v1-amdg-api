# 🚀 Quick Start Guide

Get the AMDG API running in under 5 minutes!

## Step 1: Clone and Setup Environment

```bash
git clone https://github.com/romesalarda/v1-amdg-api.git
cd v1-amdg-api
cp .env.example .env
```

## Step 2: Edit .env for Local Development

Open `.env` and set these minimum values:

```bash
# Keep it simple for local development
DEBUG=True
SECRET_KEY=your-local-secret-key-here
USE_POSTGRES=True  # or False to use SQLite
DB_PASSWORD=postgres

# Local URLs
ALLOWED_HOSTS=localhost,127.0.0.1,web
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

## Step 3: Start with Docker Compose

```bash
# Build and start all services
docker-compose up --build

# Or run in background
docker-compose up -d
```

**That's it!** 🎉

The API will be running at: http://localhost:8000

## Step 4: Create a Superuser

```bash
docker-compose exec web python manage.py createsuperuser
```

Follow the prompts to create an admin account.

## Step 5: Access Your API

- **API Root**: http://localhost:8000/api/
- **Swagger Docs**: http://localhost:8000/api/schema/swagger-ui/
- **Admin Panel**: http://localhost:8000/admin/
- **Health Check**: http://localhost:8000/api/health/

## Quick Test with cURL

### Register a new user:
```bash
curl -X POST http://localhost:8000/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "securepass123",
    "password_confirm": "securepass123"
  }'
```

### Login:
```bash
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{
    "email": "test@example.com",
    "password": "securepass123"
  }'
```

### Get your profile (using saved cookies):
```bash
curl -X GET http://localhost:8000/api/users/me/ \
  -b cookies.txt
```

## Useful Docker Commands

```bash
# View logs
docker-compose logs -f

# View logs for specific service
docker-compose logs -f web

# Stop services
docker-compose down

# Stop and remove volumes (clean slate)
docker-compose down -v

# Rebuild after code changes
docker-compose up --build

# Run Django commands
docker-compose exec web python manage.py <command>

# Access Django shell
docker-compose exec web python manage.py shell

# Run tests
docker-compose exec web python manage.py test
```

## Common Issues

### Port Already in Use
If port 8000 is already in use:
```bash
# Find and kill the process
lsof -ti:8000 | xargs kill -9  # macOS/Linux
netstat -ano | findstr :8000   # Windows (then kill in Task Manager)
```

### Database Connection Issues
Make sure PostgreSQL container is healthy:
```bash
docker-compose ps
docker-compose logs db
```

### Permission Errors on Linux
```bash
sudo chown -R $USER:$USER .
```

## What's Running?

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| Django Web | django_app | 8000 | API server |
| PostgreSQL | postgres_db | 5432 | Database |
| Redis | redis_server | 6379 | Cache & Celery broker |
| Celery Worker | celery_worker | - | Background tasks |
| Celery Beat | celery_beat | - | Scheduled tasks |
| Nginx | nginx_server | 80, 443 | Reverse proxy (production) |

## Next Steps

1. ✅ Explore the API docs at http://localhost:8000/api/schema/swagger-ui/
2. ✅ Read the full [README.md](README.md) for deployment and production setup
3. ✅ Start building your features in new Django apps
4. ✅ Configure AWS services for production (S3, SES, SSM)

## Need Help?

Check the full [README.md](README.md) or open an issue on GitHub.

---

Happy coding! 🚀
