# Image Upload Size Configuration Guide

This guide explains how to configure image upload size limits to prevent `413 Request Entity Too Large` errors.

## Problem

When uploading images to the try-on API, you may encounter:
- `413 Request Entity Too Large` error
- Uploads work locally but fail on server
- Error occurs before request reaches Django

## Root Cause

There are **multiple layers** where upload size limits are enforced:

1. **Nginx** (default: 1MB) - ⚠️ **Most common issue**
2. **Django** (default: 2.5MB)
3. **System limits** (usually not an issue)

If any layer has a limit smaller than your image size, the upload will fail.

---

## Solution: Configure All Layers

### 1. Nginx Configuration (CRITICAL)

**Location:** `/etc/nginx/sites-available/v-tryon-backend-v2`

**Add to server block:**

```nginx
server {
    listen 443 ssl http2;
    # ... other settings ...
    
    # ⚠️ CRITICAL: Must be in server block (not just location)
    client_max_body_size 50M;  # or 100M for larger images
    
    location / {
        # ⚠️ IMPORTANT: Disable buffering for large uploads
        proxy_buffering off;
        proxy_request_buffering off;
        
        proxy_pass http://gunicorn;
        # ... rest of config ...
    }
}
```

**Important Notes:**
- `client_max_body_size` must be in the `server` block, not just `location` blocks
- If you have both HTTP (port 80) and HTTPS (port 443) blocks, add it to both
- After changing, reload Nginx: `sudo systemctl reload nginx`

### 2. Django Settings

**Location:** `v_tryon_backend_v2/settings.py` or `.env` file

**Current configuration:**
```python
# File upload size limits (for large image uploads)
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000
```

**To increase to 100MB:**
```python
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024  # 100MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024  # 100MB
```

**Important:** These values should be **equal to or less than** the Nginx `client_max_body_size`.

### 3. Gunicorn Configuration

**Location:** `gunicorn_config.py`

Gunicorn doesn't directly limit upload size, but timeout settings matter:

```python
# Worker timeout in seconds
# Must be long enough for large uploads + AI processing
timeout = 1000  # ~16.7 minutes
```

This is already configured correctly in the provided `gunicorn_config.py`.

---

## Recommended Size Limits

| Use Case | Nginx | Django | Notes |
|----------|-------|--------|-------|
| **Standard Images** | 50M | 50MB | Good for most garment/person images |
| **High Resolution** | 100M | 100MB | For very detailed images |
| **Maximum** | 200M | 200MB | Not recommended to go higher |

---

## Step-by-Step Fix

### Step 1: Check Current Configuration

```bash
# Check Nginx limit
sudo nginx -T | grep client_max_body_size

# Check Django settings
grep -E "DATA_UPLOAD_MAX|FILE_UPLOAD_MAX" v_tryon_backend_v2/settings.py
```

### Step 2: Update Nginx

```bash
# Edit Nginx config
sudo nano /etc/nginx/sites-available/v-tryon-backend-v2

# Add or update:
client_max_body_size 50M;

# In location / block, add:
proxy_buffering off;
proxy_request_buffering off;

# Test configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

### Step 3: Update Django (if needed)

```bash
# Edit settings.py
nano v_tryon_backend_v2/settings.py

# Update values:
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50MB

# Restart Django service
sudo systemctl restart v-tryon-backend-v2
```

### Step 4: Verify

```bash
# Check Nginx is using new config
sudo nginx -T | grep client_max_body_size
# Should show: client_max_body_size 50M;

# Test upload
curl -X POST http://your-domain.com/v2/tryon \
  -F "person_image=@test-image.jpg" \
  -F "garment_image=@test-garment.jpg" \
  -w "\nStatus: %{http_code}\n"
```

---

## Common Issues

### Issue 1: `client_max_body_size` in wrong location

**Wrong:**
```nginx
location / {
    client_max_body_size 50M;  # ❌ Only applies to this location
    # ...
}
```

**Right:**
```nginx
server {
    client_max_body_size 50M;  # ✅ Applies to all locations
    # ...
}
```

### Issue 2: Multiple server blocks

If you have both HTTP and HTTPS blocks, add to both:

```nginx
# HTTP server
server {
    listen 80;
    client_max_body_size 50M;
    # ...
}

# HTTPS server
server {
    listen 443 ssl;
    client_max_body_size 50M;
    # ...
}
```

### Issue 3: Nginx not reloaded

After changing config, **must** reload:

```bash
sudo systemctl reload nginx
# OR
sudo nginx -s reload
```

### Issue 4: Buffering enabled

Large uploads can timeout if buffering is enabled:

```nginx
location / {
    # ❌ Wrong - can cause timeouts
    # proxy_buffering on;
    
    # ✅ Right - disable buffering
    proxy_buffering off;
    proxy_request_buffering off;
}
```

---

## Testing Upload Limits

### Test with curl

```bash
# Create a test file of specific size
dd if=/dev/zero of=test-10mb.jpg bs=1M count=10

# Test upload
curl -X POST http://your-domain.com/v2/tryon \
  -F "person_image=@test-10mb.jpg" \
  -F "garment_image=@test-10mb.jpg" \
  -w "\nStatus: %{http_code}\n" \
  -o /dev/null
```

### Check Logs

```bash
# Nginx error log
sudo tail -f /var/log/nginx/v-tryon-backend-v2-error.log

# Django logs
sudo journalctl -u v-tryon-backend-v2 -f
```

---

## Quick Reference

| Setting | Location | Default | Recommended |
|---------|----------|---------|-------------|
| `client_max_body_size` | Nginx server block | 1M | 50M |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` | Django settings | 2.5MB | 50MB |
| `FILE_UPLOAD_MAX_MEMORY_SIZE` | Django settings | 2.5MB | 50MB |
| `proxy_buffering` | Nginx location | on | off |
| `proxy_request_buffering` | Nginx location | on | off |
| `timeout` | Gunicorn config | 30s | 1000s |

---

## Additional Tips

1. **Client-side compression:** Consider compressing images before upload
2. **Progressive uploads:** For very large files, consider chunked uploads
3. **Direct cloud storage:** For production, consider direct upload to GCS/S3
4. **Monitor disk space:** Large uploads consume disk space in `/tmp`

---

**Last Updated:** December 2025

