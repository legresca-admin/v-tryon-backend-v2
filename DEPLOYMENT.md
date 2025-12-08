# V-Tryon Backend V2 - Production Deployment Guide

Complete guide for deploying the V-Tryon Backend V2 to a production server using Gunicorn.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Server Setup](#server-setup)
3. [Code Deployment](#code-deployment)
4. [Environment Configuration](#environment-configuration)
5. [Database Setup](#database-setup)
6. [Gunicorn Configuration](#gunicorn-configuration)
7. [Systemd Service Setup](#systemd-service-setup)
8. [Nginx Configuration](#nginx-configuration)
9. [SSL/HTTPS Setup](#sslhttps-setup)
10. [Google Cloud Authentication](#google-cloud-authentication)
11. [Testing Deployment](#testing-deployment)
12. [Monitoring and Logging](#monitoring-and-logging)
13. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Server Requirements

- **OS**: Ubuntu 20.04 LTS or later (recommended)
- **Python**: 3.11
- **RAM**: Minimum 2GB (4GB+ recommended)
- **CPU**: 2+ cores recommended
- **Storage**: 10GB+ free space
- **Network**: Public IP address and domain name (optional but recommended)

### Software Requirements

- Python 3.11
- pip
- virtualenv or conda
- Nginx (for reverse proxy)
- Git (for code deployment)
- gcloud CLI (for Google Cloud authentication)

---

## Step 1: Server Setup

### 1.1 Update System

```bash
sudo apt update
sudo apt upgrade -y
```

### 1.2 Install Python and Dependencies

```bash
# Install Python 3.11 and pip
sudo apt install -y python3.11 python3.11-venv python3-pip python3-dev

# Install system dependencies
sudo apt install -y build-essential libpq-dev nginx git curl
```

### 1.3 Create Application User

```bash
# Create a dedicated user for the application
sudo adduser --system --group --home /home/vtryon vtryon

# Add user to www-data group (for Nginx)
sudo usermod -aG www-data vtryon
```

### 1.4 Create Application Directory

```bash
# Create application directory
sudo mkdir -p /home/vtryon/v-tryon-backend-v2
sudo chown vtryon:vtryon /home/vtryon/v-tryon-backend-v2
```

---

## Step 2: Code Deployment

### 2.1 Clone or Upload Code

**Option A: Using Git (Recommended)**

```bash
cd /home/vtryon
sudo -u vtryon git clone <your-repository-url> v-tryon-backend-v2
cd v-tryon-backend-v2
```

**Option B: Upload via SCP**

```bash
# From your local machine
scp -r v-tryon-v2/* vtryon@your-server-ip:/home/vtryon/v-tryon-backend-v2/
```

### 2.2 Set Up Python Environment

```bash
cd /home/vtryon/v-tryon-backend-v2

# Create virtual environment
sudo -u vtryon python3.11 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt
```

---

## Step 3: Environment Configuration

### 3.1 Create Production .env File

```bash
cd /home/vtryon/v-tryon-backend-v2
sudo -u vtryon nano .env
```

Add the following configuration:

```bash
# Django Settings
SECRET_KEY=your-very-secure-secret-key-here-generate-with-openssl-rand-hex-32
DEBUG=False
ALLOWED_HOSTS=your-domain.com,www.your-domain.com,your-server-ip

# CORS Settings
CORS_ALLOW_ALL_ORIGINS=False
CORS_ALLOWED_ORIGINS=https://your-domain.com,https://www.your-domain.com

# Google Cloud Configuration
GOOGLE_CLOUD_PROJECT=gen-lang-client-0523386991
GOOGLE_CLOUD_LOCATION=asia-southeast1
# Leave empty to use Application Default Credentials (ADC)
# For production: Set to path of service account JSON key file
GOOGLE_APPLICATION_CREDENTIALS=/etc/v-tryon/secrets/gcp-service-account.json
GOOGLE_GENAI_USE_VERTEXAI=true

# Logging
DJANGO_LOG_LEVEL=INFO
```

### 3.2 Generate Secret Key

```bash
# Generate a secure secret key
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Copy the output and use it as `SECRET_KEY` in your `.env` file.

### 3.3 Set File Permissions

```bash
# Secure the .env file
chmod 600 /home/vtryon/v-tryon-backend-v2/.env
chown vtryon:vtryon /home/vtryon/v-tryon-backend-v2/.env
```

---

## Step 4: Database Setup

### 4.1 Run Migrations

```bash
cd /home/vtryon/v-tryon-backend-v2
source venv/bin/activate

# Run migrations
python manage.py migrate

# Create superuser (optional, for admin access)
python manage.py createsuperuser
```

### 4.2 Collect Static Files

```bash
# Collect static files
python manage.py collectstatic --noinput
```

This will create a `staticfiles` directory with all static files.

---

## Step 5: Gunicorn Configuration

### 5.1 Verify Gunicorn Config

The `gunicorn_config.py` file is already in the project. Review and adjust if needed:

```bash
cat /home/vtryon/v-tryon-backend-v2/gunicorn_config.py
```

Key settings to adjust:
- `workers`: Number of worker processes (default: 2 * CPU cores + 1)
- `timeout`: Worker timeout in seconds (default: 1000 for long AI requests)
- `bind`: Address and port (default: 127.0.0.1:8000)

### 5.2 Test Gunicorn Manually

```bash
cd /home/vtryon/v-tryon-backend-v2
source venv/bin/activate

# Test Gunicorn
gunicorn --config gunicorn_config.py v_tryon_backend_v2.wsgi:application
```

You should see output like:
```
[INFO] Starting gunicorn 23.0.0
[INFO] Listening at: http://127.0.0.1:8000
[INFO] Using worker: sync
[INFO] Booting worker with pid: 12345
```

Test it in another terminal:
```bash
curl http://127.0.0.1:8000/v2/current-version
```

Press `Ctrl+C` to stop Gunicorn.

---

## Step 6: Systemd Service Setup

### 6.1 Create Systemd Service File

```bash
sudo nano /etc/systemd/system/v-tryon-backend-v2.service
```

Add the following configuration:

```ini
[Unit]
Description=V-Tryon Backend V2 Django Application (Gunicorn)
After=network.target
Wants=network-online.target

[Service]
Type=notify
User=vtryon
Group=vtryon
RuntimeDirectory=v-tryon-backend-v2
WorkingDirectory=/home/vtryon/v-tryon-backend-v2

# Environment
Environment="PATH=/home/vtryon/v-tryon-backend-v2/venv/bin"
Environment="DJANGO_SETTINGS_MODULE=v_tryon_backend_v2.settings"
EnvironmentFile=/home/vtryon/v-tryon-backend-v2/.env

# Google Cloud Credentials (if using service account)
# Uncomment if using service account JSON file
# Environment="GOOGLE_APPLICATION_CREDENTIALS=/etc/v-tryon/secrets/gcp-service-account.json"

# ExecStart
ExecStart=/home/vtryon/v-tryon-backend-v2/venv/bin/gunicorn \
    --config /home/vtryon/v-tryon-backend-v2/gunicorn_config.py \
    v_tryon_backend_v2.wsgi:application

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/vtryon/v-tryon-backend-v2/media /home/vtryon/v-tryon-backend-v2/staticfiles

# Restart
Restart=always
RestartSec=3

# Timeouts
TimeoutStartSec=300
TimeoutStopSec=1200

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=v-tryon-backend-v2

[Install]
WantedBy=multi-user.target
```

### 6.2 Enable and Start Service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable v-tryon-backend-v2

# Start the service
sudo systemctl start v-tryon-backend-v2

# Check status
sudo systemctl status v-tryon-backend-v2
```

### 6.3 View Logs

```bash
# View service logs
sudo journalctl -u v-tryon-backend-v2 -f

# View recent logs
sudo journalctl -u v-tryon-backend-v2 -n 100

# View logs since boot
sudo journalctl -u v-tryon-backend-v2 -b
```

---

## Step 7: Image Upload Size Configuration

### 7.0 Understanding Image Upload Limits

The try-on API accepts image uploads, and there are **multiple places** where size limits must be configured:

1. **Nginx** (`client_max_body_size`) - Default: 1MB ⚠️ **MUST BE INCREASED**
2. **Django** (`DATA_UPLOAD_MAX_MEMORY_SIZE`, `FILE_UPLOAD_MAX_MEMORY_SIZE`) - Default: 2.5MB
3. **System limits** (usually not an issue)

**Recommended Configuration:**
- **50MB**: Good for most images (recommended starting point)
- **100MB**: For very high-resolution images
- **200MB**: Maximum recommended

**Important:** All limits must be set consistently. If Nginx allows 50MB but Django only allows 10MB, uploads will fail.

## Step 7: Nginx Configuration

### 7.1 Install Nginx (If Not Already Installed)

```bash
sudo apt install -y nginx
```

### 7.2 Create Nginx Configuration

```bash
sudo nano /etc/nginx/sites-available/v-tryon-backend-v2
```

**⚠️ IMPORTANT: Image Upload Size Configuration**

Before adding the configuration, note that the default Nginx `client_max_body_size` is **1MB**, which is too small for image uploads. The configuration below sets it to **50MB**, which should handle most garment and person images. If you need to support larger images, increase this value.

Add the following configuration:

```nginx
# Upstream Gunicorn
upstream gunicorn {
    server 127.0.0.1:8000 fail_timeout=0;
}

# HTTP Server (redirects to HTTPS)
server {
    listen 80;
    listen [::]:80;
    server_name your-domain.com www.your-domain.com;

    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

# HTTPS Server
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name your-domain.com www.your-domain.com;

    # SSL Configuration (see Step 8 for SSL setup)
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security Headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;

    # Logging
    access_log /var/log/nginx/v-tryon-backend-v2-access.log;
    error_log /var/log/nginx/v-tryon-backend-v2-error.log;

    # ⚠️ CRITICAL: Client body size (for image uploads)
    # Default is 1MB which is too small for images
    # Set to 50M for most images, 100M for very large images
    client_max_body_size 50M;

    # Proxy settings for long-running AI requests
    proxy_connect_timeout 1000s;
    proxy_send_timeout 1000s;
    proxy_read_timeout 1000s;
    send_timeout 1000s;

    # Main location
    location / {
        proxy_pass http://gunicorn;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
        
        # ⚠️ IMPORTANT: Disable buffering for large file uploads
        # This prevents Nginx from buffering the entire request in memory
        proxy_buffering off;
        proxy_request_buffering off;
        
        # WebSocket support (if needed in future)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Static files
    location /static/ {
        alias /home/vtryon/v-tryon-backend-v2/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Media files (generated try-on images)
    location /media/ {
        alias /home/vtryon/v-tryon-backend-v2/media/;
        expires 7d;
        add_header Cache-Control "public";
        
        # Allow access to generated images
        # Images are saved in: media/tryon/YYYY/MM/DD/tryon_{uuid}.png
    }
}
```

**For HTTP-only (no SSL):**

If you're not using SSL, use this simpler configuration:

```nginx
upstream gunicorn {
    server 127.0.0.1:8000 fail_timeout=0;
}

server {
    listen 80;
    listen [::]:80;
    server_name your-domain.com www.your-domain.com your-server-ip;

    # ⚠️ CRITICAL: Client body size (for image uploads)
    client_max_body_size 50M;

    proxy_connect_timeout 1000s;
    proxy_send_timeout 1000s;
    proxy_read_timeout 1000s;
    send_timeout 1000s;

    location / {
        proxy_pass http://gunicorn;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
        
        # ⚠️ IMPORTANT: Disable buffering for large file uploads
        proxy_buffering off;
        proxy_request_buffering off;
    }

    location /static/ {
        alias /home/vtryon/v-tryon-backend-v2/staticfiles/;
        expires 30d;
    }

    location /media/ {
        alias /home/vtryon/v-tryon-backend-v2/media/;
        expires 7d;
    }
}
```

### 7.3 Enable Nginx Site

```bash
# Create symbolic link
sudo ln -s /etc/nginx/sites-available/v-tryon-backend-v2 /etc/nginx/sites-enabled/

# Remove default site (optional)
sudo rm /etc/nginx/sites-enabled/default

# Test Nginx configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

---

## Step 8: SSL/HTTPS Setup (Optional but Recommended)

### 8.1 Install Certbot

```bash
sudo apt install -y certbot python3-certbot-nginx
```

### 8.2 Obtain SSL Certificate

```bash
# Replace with your domain
sudo certbot --nginx -d your-domain.com -d www.your-domain.com
```

Follow the prompts to complete the setup. Certbot will automatically configure Nginx.

### 8.3 Auto-Renewal

Certbot sets up auto-renewal automatically. Test it:

```bash
sudo certbot renew --dry-run
```

---

## Step 9: Google Cloud Authentication

### 9.1 Option A: Application Default Credentials (ADC) - Recommended for Development

If you've already run `gcloud auth application-default login` on the server:

```bash
# Set quota project
gcloud auth application-default set-quota-project gen-lang-client-0523386991

# Verify
gcloud auth application-default print-access-token
```

### 9.2 Option B: Service Account (Recommended for Production)

1. **Create Service Account in Google Cloud Console:**
   - Go to IAM & Admin > Service Accounts
   - Create new service account
   - Grant roles: `Vertex AI User`, `AI Platform User`
   - Create and download JSON key

2. **Upload Service Account Key:**

```bash
# Create secrets directory
sudo mkdir -p /etc/v-tryon/secrets
sudo chmod 700 /etc/v-tryon/secrets

# Upload your service account JSON file
sudo nano /etc/v-tryon/secrets/gcp-service-account.json
# Paste the JSON content

# Set permissions
sudo chmod 600 /etc/v-tryon/secrets/gcp-service-account.json
sudo chown vtryon:vtryon /etc/v-tryon/secrets/gcp-service-account.json
```

3. **Update .env file:**

```bash
# In .env file
GOOGLE_APPLICATION_CREDENTIALS=/etc/v-tryon/secrets/gcp-service-account.json
```

4. **Update systemd service** (uncomment the line in service file):

```ini
Environment="GOOGLE_APPLICATION_CREDENTIALS=/etc/v-tryon/secrets/gcp-service-account.json"
```

---

## Step 10: Testing Deployment

### 10.1 Test API Endpoints

```bash
# Test version endpoint
curl http://your-domain.com/v2/current-version

# Test try-on endpoint (with images)
# Returns JSON with image URL
curl -X POST http://your-domain.com/v2/tryon \
  -F "person_image=@person.jpg" \
  -F "garment_image=@garment.jpg"

# Response will be JSON:
# {
#   "success": true,
#   "image_url": "http://your-domain.com/media/tryon/2025/12/08/tryon_abc123.png",
#   "message": "Try-on image generated successfully",
#   ...
# }

# Access the generated image:
curl http://your-domain.com/media/tryon/2025/12/08/tryon_abc123.png --output result.png
```

### 10.2 Check Service Status

```bash
# Check Gunicorn service
sudo systemctl status v-tryon-backend-v2

# Check Nginx
sudo systemctl status nginx

# Check logs
sudo journalctl -u v-tryon-backend-v2 -n 50
```

### 10.3 Test Rate Limiting

```bash
# Make multiple requests to test rate limiting
for i in {1..12}; do
  echo "Request $i:"
  curl -X POST http://your-domain.com/v2/tryon \
    -F "person_image=@person.jpg" \
    -F "garment_image=@garment.jpg" \
    -w "\nStatus: %{http_code}\n" \
    -o /dev/null
  sleep 1
done
```

---

## Step 11: Monitoring and Logging

### 11.1 View Application Logs

```bash
# Real-time logs
sudo journalctl -u v-tryon-backend-v2 -f

# Last 100 lines
sudo journalctl -u v-tryon-backend-v2 -n 100

# Logs since today
sudo journalctl -u v-tryon-backend-v2 --since today
```

### 11.2 View Nginx Logs

```bash
# Access logs
sudo tail -f /var/log/nginx/v-tryon-backend-v2-access.log

# Error logs
sudo tail -f /var/log/nginx/v-tryon-backend-v2-error.log
```

### 11.3 Monitor System Resources

```bash
# CPU and memory usage
htop

# Disk usage
df -h

# Check Gunicorn processes
ps aux | grep gunicorn
```

---

## Step 12: Common Operations

### 12.1 Restart Service

```bash
# Restart the application
sudo systemctl restart v-tryon-backend-v2

# Reload Nginx
sudo systemctl reload nginx
```

### 12.2 Update Code

```bash
cd /home/vtryon/v-tryon-backend-v2

# Pull latest code (if using Git)
sudo -u vtryon git pull

# Activate virtual environment
source venv/bin/activate

# Install new dependencies (if any)
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput

# Restart service
sudo systemctl restart v-tryon-backend-v2
```

### 12.3 Update Environment Variables

```bash
# Edit .env file
sudo -u vtryon nano /home/vtryon/v-tryon-backend-v2/.env

# Restart service to apply changes
sudo systemctl restart v-tryon-backend-v2
```

---

## Troubleshooting

### Issue: 413 Request Entity Too Large (Image Upload Error)

**Symptoms:**
- Getting `413 Request Entity Too Large` error when uploading images
- Uploads work locally but fail on server
- Error occurs before request reaches Django

**Root Cause:**
Nginx has a default `client_max_body_size` of **1MB**, which is too small for image uploads.

**Solution:**

1. **Check current Nginx configuration:**
   ```bash
   sudo nginx -T | grep client_max_body_size
   ```

2. **Update Nginx configuration:**
   ```bash
   sudo nano /etc/nginx/sites-available/v-tryon-backend-v2
   ```
   
   Make sure `client_max_body_size` is set in the `server` block (not just in location blocks):
   ```nginx
   server {
       listen 443 ssl http2;
       # ... other settings ...
       
       # ⚠️ CRITICAL: Must be in server block
       client_max_body_size 50M;  # or 100M for larger images
       
       location / {
           # Also add these for large uploads
           proxy_buffering off;
           proxy_request_buffering off;
           # ... rest of config ...
       }
   }
   ```

3. **Update Django settings** (if needed):
   ```bash
   # Edit settings.py or .env
   # Make sure these match or are less than Nginx limit:
   DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50MB
   FILE_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50MB
   ```

4. **Test and reload:**
   ```bash
   # Test Nginx configuration
   sudo nginx -t
   
   # Reload Nginx
   sudo systemctl reload nginx
   
   # Restart Django service
   sudo systemctl restart v-tryon-backend-v2
   ```

5. **Verify the fix:**
   ```bash
   # Check Nginx is using new config
   sudo nginx -T | grep client_max_body_size
   
   # Should show: client_max_body_size 50M;
   ```

**Recommended Sizes:**
- **50MB**: Good for most garment and person images (recommended)
- **100MB**: For very high-resolution images
- **200MB**: Maximum recommended (very large images)

**Note:** If you have both HTTP (port 80) and HTTPS (port 443) server blocks, add `client_max_body_size` to both.

### Issue: Service fails to start

**Check logs:**
```bash
sudo journalctl -u v-tryon-backend-v2 -n 50
```

**Common causes:**
- Missing environment variables in `.env`
- Incorrect file permissions
- Python dependencies not installed
- Database connection issues

### Issue: 502 Bad Gateway

**Check:**
1. Is Gunicorn running?
   ```bash
   sudo systemctl status v-tryon-backend-v2
   ```

2. Check Gunicorn logs:
   ```bash
   sudo journalctl -u v-tryon-backend-v2 -n 100
   ```

3. Test Gunicorn directly:
   ```bash
   curl http://127.0.0.1:8000/v2/current-version
   ```

### Issue: Timeout errors

**Solution:**
- Increase timeout in `gunicorn_config.py` (already set to 1000s)
- Increase Nginx timeouts in configuration
- Check system resources (CPU, memory)

### Issue: Static files not loading

**Solution:**
```bash
# Collect static files again
cd /home/vtryon/v-tryon-backend-v2
source venv/bin/activate
python manage.py collectstatic --noinput

# Check permissions
sudo chown -R vtryon:vtryon /home/vtryon/v-tryon-backend-v2/staticfiles
```

### Issue: Image uploads timeout or fail silently

**Symptoms:**
- Upload starts but never completes
- No error message, just hangs
- Works for small images but fails for large ones

**Solution:**

1. **Check all timeout settings are consistent:**
   - Nginx: `proxy_read_timeout 1000s` (in nginx config)
   - Gunicorn: `timeout = 1000` (in gunicorn_config.py)
   - Django: Already configured for long requests

2. **Verify proxy buffering is disabled:**
   ```nginx
   location / {
       proxy_buffering off;
       proxy_request_buffering off;
       # ... rest of config ...
   }
   ```

3. **Check system resources:**
   ```bash
   # Check disk space
   df -h
   
   # Check memory
   free -h
   
   # Check if processes are running
   ps aux | grep gunicorn
   ```

4. **Test with curl to see actual error:**
   ```bash
   curl -v -X POST http://your-domain.com/v2/tryon \
     -F "person_image=@large-image.jpg" \
     -F "garment_image=@large-garment.jpg" \
     --max-time 1200
   ```

### Issue: Google Cloud authentication errors

**Check:**
1. Verify credentials:
   ```bash
   sudo -u vtryon gcloud auth application-default print-access-token
   ```

2. Check service account permissions (if using service account)

3. Verify project ID in `.env` matches your Google Cloud project

### Issue: Rate limiting not working

**Check:**
1. Verify cache is working:
   ```bash
   python manage.py shell
   >>> from django.core.cache import cache
   >>> cache.set('test', 'value')
   >>> cache.get('test')
   ```

2. Check rate limit status:
   ```bash
   python manage.py ratelimit status <ip_address>
   ```

---

## Security Checklist

- [ ] `DEBUG=False` in production `.env`
- [ ] Strong `SECRET_KEY` generated
- [ ] `.env` file permissions set to 600
- [ ] Service account JSON key secured (600 permissions)
- [ ] Firewall configured (only allow 80, 443, 22)
- [ ] SSL/HTTPS enabled
- [ ] `ALLOWED_HOSTS` configured correctly
- [ ] CORS settings configured for your domain
- [ ] Regular security updates applied

---

## Backup Strategy

### Database Backup

```bash
# Backup SQLite database
cp /home/vtryon/v-tryon-backend-v2/db.sqlite3 /backup/db-$(date +%Y%m%d).sqlite3
```

### Code Backup

```bash
# Backup entire application directory
tar -czf /backup/v-tryon-backend-v2-$(date +%Y%m%d).tar.gz /home/vtryon/v-tryon-backend-v2
```

---

## Performance Tuning

### Adjust Gunicorn Workers

Edit `gunicorn_config.py`:

```python
# For CPU-bound tasks (AI image generation)
workers = multiprocessing.cpu_count() * 2 + 1

# For I/O-bound tasks
worker_class = "gevent"
worker_connections = 1000
```

### Enable Caching

For production, consider using Redis or Memcached:

```python
# In settings.py
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
    }
}
```

---

## Support

For issues or questions:
1. Check logs: `sudo journalctl -u v-tryon-backend-v2 -f`
2. Review this deployment guide
3. Check Django documentation: https://docs.djangoproject.com/
4. Check Gunicorn documentation: https://docs.gunicorn.org/

---

**Last Updated:** December 2025
**Version:** 1.0

