# Rate Limiting Documentation

## Overview

The V-Tryon API v2 implements rate limiting to prevent abuse and ensure fair usage. Rate limits are applied per IP address and are tracked independently for hourly and daily limits.

## Rate Limits

- **Hourly Limit**: 10 requests per hour per IP
- **Daily Limit**: 40 requests per day per IP

Both limits are enforced independently. If either limit is exceeded, the request will be rejected.

## How It Works

### IP Address Detection

The system automatically detects the client IP address from:
1. `X-Forwarded-For` header (for requests behind proxies)
2. `X-Real-IP` header (for nginx reverse proxies)
3. `REMOTE_ADDR` (direct connection)

### Rate Limit Tracking

Rate limits are tracked using Django's cache system (LocMemCache by default). Each IP address has two counters:
- Hourly counter: Resets every hour
- Daily counter: Resets every 24 hours

### Response Headers

Successful API responses include rate limit information in headers:

```
X-RateLimit-Limit-Hourly: 10
X-RateLimit-Remaining-Hourly: 5
X-RateLimit-Limit-Daily: 40
X-RateLimit-Remaining-Daily: 20
```

### Error Response

When rate limit is exceeded, the API returns:

**Status Code**: `429 Too Many Requests`

**Response Body**:
```json
{
    "error": "Rate limit exceeded",
    "message": "You have exceeded the hourly rate limit of 10 requests per hour. Please try again later.",
    "rate_limit": {
        "type": "hourly",
        "limit": 10,
        "current": 11,
        "retry_after": "1 hour"
    }
}
```

## Management Commands

### Check Rate Limit Status

Check the current rate limit status for a specific IP:

```bash
python manage.py ratelimit status <ip_address>
```

Example:
```bash
python manage.py ratelimit status 192.168.1.100
```

Output:
```
Rate Limit Status for IP: 192.168.1.100
============================================================
Hourly Limit: 5/10 (50.0% used)
  Remaining: 5 requests

Daily Limit: 15/40 (37.5% used)
  Remaining: 25 requests
============================================================
```

### Reset Rate Limit

Reset rate limits for a specific IP address:

```bash
python manage.py ratelimit reset <ip_address>
```

Example:
```bash
python manage.py ratelimit reset 192.168.1.100
```

This will reset both hourly and daily counters for the specified IP.

## Configuration

Rate limiting is configured in `settings.py`:

```python
# Cache configuration for rate limiting
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}

# Rate limiting configuration
RATELIMIT_ENABLE = os.getenv('RATELIMIT_ENABLE', 'true').lower() == 'true'
RATELIMIT_USE_CACHE = 'default'
```

### Production Recommendations

For production environments, consider using Redis or Memcached instead of LocMemCache:

```python
# Redis example
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
    }
}
```

Benefits:
- Persistent rate limit tracking across server restarts
- Shared rate limit state across multiple server instances
- Better performance for high-traffic applications

## Testing Rate Limits

### Using curl

```bash
# Make multiple requests to test rate limiting
for i in {1..12}; do
  echo "Request $i:"
  curl -X POST http://localhost:8000/v2/tryon \
    -F "person_image=@person.jpg" \
    -F "garment_image=@garment.jpg" \
    -w "\nStatus: %{http_code}\n" \
    -o /dev/null
  sleep 1
done
```

### Expected Behavior

- Requests 1-10: Should succeed (200 OK)
- Request 11: Should fail with 429 Too Many Requests (hourly limit)
- After 1 hour: Counter resets, requests can succeed again

## Logging

Rate limit events are logged with the following levels:

- **INFO**: Normal API requests with rate limit status
- **WARNING**: Rate limit exceeded
- **DEBUG**: Detailed rate limit status for each request

Example log entries:
```
INFO: API v2 try-on request received from IP=192.168.1.100
DEBUG: API v2: Rate limit status for IP=192.168.1.100 - Hourly: 5/10 (remaining: 5), Daily: 15/40 (remaining: 25)
WARNING: API v2: Rate limit exceeded (hourly) for IP=192.168.1.100 - Current: 11/10
```

## Troubleshooting

### Rate limits not working

1. Check that `RATELIMIT_ENABLE` is set to `'true'` in settings
2. Verify cache is working: `python manage.py shell` then `from django.core.cache import cache; cache.set('test', 'value'); cache.get('test')`
3. Check logs for rate limit warnings

### Need to reset limits for testing

Use the management command:
```bash
python manage.py ratelimit reset <ip_address>
```

### Rate limits resetting too quickly

This usually indicates cache is not persisting. Switch to Redis or Memcached in production.

## Security Considerations

1. **IP Spoofing**: Rate limits are based on IP addresses. Users behind NAT or VPNs share the same IP and limits.

2. **Distributed Attacks**: For production, use Redis/Memcached to share rate limit state across multiple servers.

3. **Bypass Attempts**: The system checks both `X-Forwarded-For` and `REMOTE_ADDR` to prevent header spoofing.

4. **Monitoring**: Monitor rate limit warnings in logs to detect abuse patterns.

