# 🚀 Production Deployment Checklist

Complete guide for deploying AMDG API to AWS EC2.

## Prerequisites

- [ ] AWS Account with appropriate permissions
- [ ] EC2 instance running (t2.medium or larger recommended)
- [ ] Domain name configured (rsalarda.works)
- [ ] Cloudflare account (optional but recommended)
- [ ] GitHub repository set up

## 1. AWS Setup

### ECR (Elastic Container Registry)
```bash
# Create ECR repository
aws ecr create-repository \
  --repository-name amdg \
  --region eu-west-2

# Note the repositoryUri for later
```

### SSM Parameter Store
Store these secrets in AWS SSM Parameter Store:

```bash
# Set environment prefix
PREFIX="/prod/amdg/v1"

# Required parameters (max 10 for batch read!)
aws ssm put-parameter --name "${PREFIX}/SECRET_KEY" --value "your-secret-key" --type SecureString
aws ssm put-parameter --name "${PREFIX}/DEBUG" --value "False" --type String
aws ssm put-parameter --name "${PREFIX}/ALLOWED_HOSTS" --value "rsalarda.works,www.rsalarda.works" --type String
aws ssm put-parameter --name "${PREFIX}/DB_ENGINE" --value "django.db.backends.postgresql" --type String
aws ssm put-parameter --name "${PREFIX}/DB_NAME" --value "amdg_prod" --type String
aws ssm put-parameter --name "${PREFIX}/DB_USER" --value "postgres" --type String
aws ssm put-parameter --name "${PREFIX}/DB_PASSWORD" --value "your-db-password" --type SecureString
aws ssm put-parameter --name "${PREFIX}/DB_HOST" --value "db" --type String
aws ssm put-parameter --name "${PREFIX}/DB_PORT" --value "5432" --type String
```

### S3 Bucket for Static/Media Files
```bash
# Create bucket
aws s3 mb s3://amdg-static-media --region eu-west-2

# Configure bucket policy for public read
```

### IAM Role for EC2
Ensure your EC2 instance has an IAM role with these permissions:
- `AmazonEC2ContainerRegistryReadOnly`
- `AmazonSSMReadOnlyAccess`
- `AmazonS3FullAccess` (or specific bucket access)

## 2. EC2 Instance Setup

### Initial Setup
```bash
# SSH into EC2
ssh -i your-key.pem ubuntu@your-ec2-ip

# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
sudo apt-get install -y docker.io
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ubuntu

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Install AWS CLI
sudo apt-get install -y awscli

# Log out and back in for docker group to take effect
exit
```

### Clone Repository
```bash
cd /home/ubuntu
git clone https://github.com/romesalarda/v1-amdg-api.git app
cd app
```

### Configure Environment
```bash
# No .env file needed! Use SSM Parameter Store
# Just set these for Docker
export USE_SSM=True
export SSM_PARAM_PREFIX=/prod/amdg/v1/
export AWS_REGION=eu-west-2
export ECR_REGISTRY=<your-account-id>.dkr.ecr.eu-west-2.amazonaws.com
export IMAGE_TAG=latest
```

## 3. SSL Certificate Setup

### Using Let's Encrypt (Certbot)
```bash
# Install Certbot
sudo apt-get install -y certbot

# Stop nginx if running
sudo docker-compose down

# Obtain certificate (standalone mode)
sudo certbot certonly --standalone \
  -d rsalarda.works \
  -d www.rsalarda.works \
  --email your-email@example.com \
  --agree-tos \
  --non-interactive

# Certificates are saved at:
# /etc/letsencrypt/live/rsalarda.works/fullchain.pem
# /etc/letsencrypt/live/rsalarda.works/privkey.pem

# Set up auto-renewal
sudo crontab -e
# Add this line:
# 0 0 * * 0 certbot renew --quiet && docker-compose restart nginx
```

### Update nginx.conf
Ensure [nginx/nginx.conf](nginx/nginx.conf) points to correct certificate paths:
```nginx
ssl_certificate /etc/letsencrypt/live/rsalarda.works/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/rsalarda.works/privkey.pem;
```

## 4. Cloudflare Setup

1. Add your domain to Cloudflare
2. Update nameservers at your domain registrar
3. Create A record: `rsalarda.works` → EC2 IP
4. Create A record: `www.rsalarda.works` → EC2 IP
5. SSL/TLS mode: Full (strict)
6. Enable:
   - [ ] Always Use HTTPS
   - [ ] Automatic HTTPS Rewrites
   - [ ] HTTP Strict Transport Security (HSTS)

## 5. GitHub Actions Setup

### Required Secrets
Go to GitHub repo → Settings → Secrets and add:

```
AWS_ACCOUNT_ID=123456789012
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
EC2_INSTANCE_ID=i-0123456789abcdef0
TEST_DB_PASSWORD=test_password_for_ci
```

### Test the Pipeline
```bash
# Push to main branch triggers deployment
git push origin main
```

## 6. First Deployment

### Login to ECR
```bash
aws ecr get-login-password --region eu-west-2 | \
  docker login --username AWS --password-stdin \
  <account-id>.dkr.ecr.eu-west-2.amazonaws.com
```

### Pull and Start Services
```bash
# Pull latest images
docker-compose pull

# Start services
docker-compose up -d

# Check status
docker-compose ps
```

### Run Initial Migrations
```bash
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser
docker-compose exec web python manage.py collectstatic --noinput
```

## 7. Verify Deployment

### Health Check
```bash
curl https://rsalarda.works/api/health/
```

### Check Services
```bash
# View logs
docker-compose logs -f

# Check individual services
docker-compose logs web
docker-compose logs db
docker-compose logs redis
docker-compose logs celery_worker
```

### Test API
```bash
# Register a user
curl -X POST https://rsalarda.works/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "securepass123",
    "password_confirm": "securepass123"
  }'
```

## 8. Monitoring Setup

### Enable Sentry
Add to SSM (if using Sentry):
```bash
aws ssm put-parameter \
  --name "/prod/amdg/v1/SENTRY_ENABLED" \
  --value "True" \
  --type String

aws ssm put-parameter \
  --name "/prod/amdg/v1/SENTRY_DSN" \
  --value "https://...@sentry.io/..." \
  --type SecureString
```

Restart services:
```bash
docker-compose restart
```

### CloudWatch (Optional)
Set up CloudWatch agent for EC2 metrics and logs.

## 9. Backup Strategy

### Database Backups
```bash
# Create backup script
cat > /home/ubuntu/backup-db.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
docker-compose exec -T db pg_dump -U postgres amdg_prod | gzip > /home/ubuntu/backups/db_backup_$DATE.sql.gz
# Upload to S3
aws s3 cp /home/ubuntu/backups/db_backup_$DATE.sql.gz s3://your-backup-bucket/
# Keep only last 7 days locally
find /home/ubuntu/backups -name "db_backup_*.sql.gz" -mtime +7 -delete
EOF

chmod +x /home/ubuntu/backup-db.sh

# Add to crontab (daily at 2 AM)
crontab -e
# Add: 0 2 * * * /home/ubuntu/backup-db.sh
```

## 10. Security Hardening

- [ ] Change default SSH port
- [ ] Set up fail2ban
- [ ] Configure AWS Security Groups (only allow 80, 443, and your SSH)
- [ ] Enable AWS GuardDuty
- [ ] Set up AWS Config rules
- [ ] Rotate secrets regularly
- [ ] Enable CloudTrail for audit logs

## 11. Performance Optimization

### Database
```sql
-- Connect to PostgreSQL
docker-compose exec db psql -U postgres amdg_prod

-- Create indexes for common queries
CREATE INDEX idx_users_email ON users_communityuser(email);
CREATE INDEX idx_users_oauth ON users_communityuser(oauth_provider, oauth_id);
```

### Nginx Caching
Add to nginx.conf:
```nginx
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=api_cache:10m max_size=100m;
```

## 12. Rollback Plan

If deployment fails:
```bash
# Pull previous version
export IMAGE_TAG=<previous-commit-sha>
docker-compose pull
docker-compose up -d

# Or rollback database
docker-compose exec -T db psql -U postgres amdg_prod < /home/ubuntu/backups/db_backup_YYYYMMDD.sql
```

## Post-Deployment

- [ ] Verify all API endpoints work
- [ ] Test authentication flow
- [ ] Check Celery tasks are running
- [ ] Verify WebSocket connections
- [ ] Test file uploads to S3
- [ ] Send test emails
- [ ] Test Stripe integration
- [ ] Monitor logs for errors
- [ ] Set up uptime monitoring (e.g., UptimeRobot)

## Maintenance

### Regular Tasks
- Weekly: Review logs for errors
- Monthly: Update dependencies (`docker-compose pull`)
- Quarterly: Review and rotate secrets
- As needed: Scale EC2 instance if performance issues

### Updates
```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker-compose up -d --build

# Run migrations
docker-compose exec web python manage.py migrate
```

---

## Troubleshooting

### Services won't start
```bash
docker-compose logs
docker-compose ps
docker system prune -a  # Clean up
```

### Database connection issues
```bash
docker-compose logs db
docker-compose exec db psql -U postgres
```

### SSL certificate issues
```bash
sudo certbot renew --dry-run
sudo certbot certificates
```

### High CPU/Memory
```bash
# Check resource usage
docker stats

# Scale down Celery concurrency in docker-compose.yml
# command: celery -A core worker --loglevel=info --concurrency=1
```

---

**Need help?** Check the main [README.md](README.md) or contact the team.
