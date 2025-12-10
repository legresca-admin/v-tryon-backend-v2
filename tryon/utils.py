"""
Utility functions for rate limiting and user tracking
"""

import logging
from django.core.cache import cache
from django_ratelimit.core import is_ratelimited
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


def get_client_ip(request):
    """
    Get the client IP address from the request.
    Handles proxy headers (X-Forwarded-For, X-Real-IP) for production deployments.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', 'unknown')
    return ip


def get_rate_limit_status(request, rate_type='hourly'):
    """
    Get current rate limit usage information for the client.
    Uses our own tracking cache keys that sync with django-ratelimit.
    
    Args:
        request: Django request object
        rate_type: 'hourly' or 'daily'
    
    Returns:
        dict with keys: current_count, limit, remaining, percentage_used
    """
    client_ip = get_client_ip(request)
    
    if rate_type == 'hourly':
        group = 'tryon_v2_hourly'
        limit = 10
        cache_ttl = 3600  # 1 hour
    else:  # daily
        group = 'tryon_v2_daily'
        limit = 40
        cache_ttl = 86400  # 24 hours
    
    # Use our own cache key for tracking (separate from django-ratelimit's internal keys)
    # This ensures we can always read the count
    our_cache_key = f'tryon_rate_limit_{group}_{client_ip}'
    
    # Get count from our tracking cache
    current_count = cache.get(our_cache_key, 0)
    
    # If count is None or invalid, default to 0
    if current_count is None:
        current_count = 0
    else:
        try:
            current_count = int(current_count)
        except (ValueError, TypeError):
            current_count = 0
    
    remaining = max(0, limit - current_count)
    percentage_used = (current_count / limit * 100) if limit > 0 else 0
    
    return {
        'current_count': current_count,
        'limit': limit,
        'remaining': remaining,
        'percentage_used': round(percentage_used, 2),
        'ip': client_ip
    }


def increment_rate_limit_count(request, rate_type='hourly'):
    """
    Increment our own rate limit counter.
    This is called after django-ratelimit's check passes.
    
    Args:
        request: Django request object
        rate_type: 'hourly' or 'daily'
    """
    client_ip = get_client_ip(request)
    
    if rate_type == 'hourly':
        group = 'tryon_v2_hourly'
        cache_ttl = 3600  # 1 hour
    else:  # daily
        group = 'tryon_v2_daily'
        cache_ttl = 86400  # 24 hours
    
    our_cache_key = f'tryon_rate_limit_{group}_{client_ip}'
    
    # Get current count and increment
    current_count = cache.get(our_cache_key, 0)
    if current_count is None:
        current_count = 0
    
    try:
        current_count = int(current_count)
    except (ValueError, TypeError):
        current_count = 0
    
    # Increment
    new_count = current_count + 1
    
    # Store with TTL
    cache.set(our_cache_key, new_count, cache_ttl)
    
    logger.debug("Incremented rate limit for IP=%s, type=%s, count=%d", client_ip, rate_type, new_count)


def reset_rate_limit_for_ip(ip_address, rate_type='both'):
    """
    Reset rate limit for a specific IP address.
    Uses django-ratelimit's cache key format.
    
    Args:
        ip_address: IP address to reset
        rate_type: 'hourly', 'daily', or 'both'
    
    Returns:
        bool: True if reset was successful
    """
    from django.test import RequestFactory
    
    try:
        # Create a mock request to generate proper cache keys
        factory = RequestFactory()
        request = factory.post('/v2/tryon')
        request.META['REMOTE_ADDR'] = ip_address
        
        if rate_type in ('hourly', 'both'):
            from django_ratelimit.core import _get_cache_key
            cache_key_hourly = _get_cache_key(
                request=request,
                group='tryon_v2_hourly',
                key='ip',
                rate='10/h',
                method='POST'
            )
            cache.delete(cache_key_hourly)
            logger.info("Reset hourly rate limit for IP=%s", ip_address)
        
        if rate_type in ('daily', 'both'):
            from django_ratelimit.core import _get_cache_key
            cache_key_daily = _get_cache_key(
                request=request,
                group='tryon_v2_daily',
                key='ip',
                rate='40/d',
                method='POST'
            )
            cache.delete(cache_key_daily)
            logger.info("Reset daily rate limit for IP=%s", ip_address)
        
        return True
    except Exception as e:
        logger.error("Error resetting rate limit for IP=%s: %s", ip_address, str(e))
        return False


def check_rate_limit(request):
    """
    Check if request would be rate limited without incrementing the counter.
    
    Returns:
        dict with keys: allowed, hourly_status, daily_status
    """
    client_ip = get_client_ip(request)
    
    hourly_status = get_rate_limit_status(request, 'hourly')
    daily_status = get_rate_limit_status(request, 'daily')
    
    # Check if either limit would be exceeded
    hourly_exceeded = hourly_status['current_count'] >= hourly_status['limit']
    daily_exceeded = daily_status['current_count'] >= daily_status['limit']
    
    allowed = not (hourly_exceeded or daily_exceeded)
    
    return {
        'allowed': allowed,
        'hourly_status': hourly_status,
        'daily_status': daily_status,
        'ip': client_ip
    }


def get_rate_limit_status_device(deviceId, rate_type='hourly'):
    """
    Get current rate limit usage information for a device.
    
    Args:
        deviceId: Device identifier string
        rate_type: 'hourly' or 'daily'
    
    Returns:
        dict with keys: current_count, limit, remaining, percentage_used
    """
    # Sanitize deviceId for cache key safety (strip whitespace and newlines)
    deviceId = str(deviceId).strip()
    
    if rate_type == 'hourly':
        group = 'tryon_v2_hourly'
        limit = 10
        cache_ttl = 3600  # 1 hour
    else:  # daily
        group = 'tryon_v2_daily'
        limit = 40
        cache_ttl = 86400  # 24 hours
    
    our_cache_key = f'tryon_rate_limit_{group}_device_{deviceId}'
    
    # Get count from our tracking cache
    current_count = cache.get(our_cache_key, 0)
    
    # If count is None or invalid, default to 0
    if current_count is None:
        current_count = 0
    else:
        try:
            current_count = int(current_count)
        except (ValueError, TypeError):
            current_count = 0
    
    remaining = max(0, limit - current_count)
    percentage_used = (current_count / limit * 100) if limit > 0 else 0
    
    return {
        'current_count': current_count,
        'limit': limit,
        'remaining': remaining,
        'percentage_used': round(percentage_used, 2),
        'deviceId': deviceId
    }


def increment_rate_limit_count_device(deviceId, rate_type='hourly'):
    """
    Increment rate limit counter for a device.
    
    Args:
        deviceId: Device identifier string
        rate_type: 'hourly' or 'daily'
    """
    # Sanitize deviceId for cache key safety (strip whitespace and newlines)
    deviceId = str(deviceId).strip()
    
    if rate_type == 'hourly':
        group = 'tryon_v2_hourly'
        cache_ttl = 3600  # 1 hour
    else:  # daily
        group = 'tryon_v2_daily'
        cache_ttl = 86400  # 24 hours
    
    our_cache_key = f'tryon_rate_limit_{group}_device_{deviceId}'
    
    # Get current count and increment
    current_count = cache.get(our_cache_key, 0)
    if current_count is None:
        current_count = 0
    
    try:
        current_count = int(current_count)
    except (ValueError, TypeError):
        current_count = 0
    
    # Increment
    new_count = current_count + 1
    
    # Store with TTL
    cache.set(our_cache_key, new_count, cache_ttl)
    
    logger.debug("Incremented rate limit for deviceId=%s, type=%s, count=%d", deviceId, rate_type, new_count)


def check_rate_limit_device(deviceId):
    """
    Check if device would be rate limited without incrementing the counter.
    
    Args:
        deviceId: Device identifier string
    
    Returns:
        dict with keys: allowed, hourly_status, daily_status
    """
    # Sanitize deviceId for cache key safety (strip whitespace and newlines)
    deviceId = str(deviceId).strip()
    
    hourly_status = get_rate_limit_status_device(deviceId, 'hourly')
    daily_status = get_rate_limit_status_device(deviceId, 'daily')
    
    # Check if either limit would be exceeded
    hourly_exceeded = hourly_status['current_count'] >= hourly_status['limit']
    daily_exceeded = daily_status['current_count'] >= daily_status['limit']
    
    allowed = not (hourly_exceeded or daily_exceeded)
    
    return {
        'allowed': allowed,
        'hourly_status': hourly_status,
        'daily_status': daily_status,
        'deviceId': deviceId
    }


# ============================================================================
# User-based Rate Limiting Functions
# ============================================================================

def get_user_rate_limit(user):
    """
    Get UserRateLimit instance for the given user (does not create if missing).
    
    Args:
        user: Django User instance
    
    Returns:
        UserRateLimit instance or None if not set by admin
    """
    from users.models import UserRateLimit
    
    try:
        return UserRateLimit.objects.get(user=user)
    except UserRateLimit.DoesNotExist:
        return None


def get_or_create_user_rate_limit(user):
    """
    Get or create a UserRateLimit instance for the given user.
    Used by admin to create rate limits.
    
    Args:
        user: Django User instance
    
    Returns:
        UserRateLimit instance
    """
    from users.models import UserRateLimit
    
    rate_limit, created = UserRateLimit.objects.get_or_create(
        user=user,
        defaults={'limit': 0, 'used_count': 0}
    )
    
    if created:
        logger.info("Created new UserRateLimit for user=%s (ID: %d)", user.username, user.id)
    
    return rate_limit


def get_user_rate_limit_status(user):
    """
    Get current rate limit usage information for a user.
    
    Args:
        user: Django User instance
    
    Returns:
        dict with keys: current_count, limit, remaining, percentage_used, is_unlimited, exists
    """
    rate_limit = get_user_rate_limit(user)
    
    # If no rate limit exists, return status indicating it's not set
    if rate_limit is None:
        return {
            'current_count': 0,
            'limit': 0,
            'remaining': 0,
            'percentage_used': 0,
            'is_unlimited': False,
            'exists': False,
            'user_id': user.id,
            'username': user.username
        }
    
    limit = rate_limit.limit
    used_count = rate_limit.used_count
    is_unlimited = (limit == 0)
    
    if is_unlimited:
        remaining = None
        percentage_used = 0
    else:
        remaining = max(0, limit - used_count)
        percentage_used = (used_count / limit * 100) if limit > 0 else 0
    
    return {
        'current_count': used_count,
        'limit': limit,
        'remaining': remaining,
        'percentage_used': round(percentage_used, 2),
        'is_unlimited': is_unlimited,
        'exists': True,
        'user_id': user.id,
        'username': user.username
    }


def check_user_rate_limit(user):
    """
    Check if user would be rate limited without incrementing the counter.
    Returns False if no rate limit is set by admin.
    
    Args:
        user: Django User instance
    
    Returns:
        dict with keys: allowed, status
    """
    status = get_user_rate_limit_status(user)
    
    # If no rate limit exists, user is not allowed
    if not status.get('exists', True):
        allowed = False
    # If unlimited, always allowed
    elif status['is_unlimited']:
        allowed = True
    else:
        # Check if limit is exceeded
        allowed = not (status['current_count'] >= status['limit'])
    
    return {
        'allowed': allowed,
        'status': status
    }


def increment_user_rate_limit(user):
    """
    Increment rate limit counter for a user.
    Only increments if rate limit exists and is not unlimited.
    
    Args:
        user: Django User instance
    
    Returns:
        dict with updated status
    """
    rate_limit = get_user_rate_limit(user)
    
    # If no rate limit exists, do nothing
    if rate_limit is None:
        logger.warning(
            "Cannot increment rate limit for user=%s (ID: %d) - no rate limit set by admin",
            user.username, user.id
        )
        return get_user_rate_limit_status(user)
    
    # Only increment if not unlimited
    if rate_limit.limit > 0:
        rate_limit.increment_usage()
        logger.debug(
            "Incremented rate limit for user=%s (ID: %d), count=%d/%d",
            user.username, user.id, rate_limit.used_count, rate_limit.limit
        )
    else:
        logger.debug(
            "User=%s (ID: %d) has unlimited rate limit, skipping increment",
            user.username, user.id
        )
    
    return get_user_rate_limit_status(user)