"""
Utility functions for rate limiting and user tracking
"""

import logging
from django.core.cache import cache
from django_ratelimit.core import is_ratelimited

logger = logging.getLogger(__name__)


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
    
    Args:
        request: Django request object
        rate_type: 'hourly' or 'daily'
    
    Returns:
        dict with keys: current_count, limit, remaining, percentage_used
    """
    client_ip = get_client_ip(request)
    
    if rate_type == 'hourly':
        cache_key = f'ratelimit:tryon_v2_hourly:{client_ip}'
        limit = 10
    else:  # daily
        cache_key = f'ratelimit:tryon_v2_daily:{client_ip}'
        limit = 40
    
    current_count = cache.get(cache_key, 0)
    remaining = max(0, limit - current_count)
    percentage_used = (current_count / limit * 100) if limit > 0 else 0
    
    return {
        'current_count': current_count,
        'limit': limit,
        'remaining': remaining,
        'percentage_used': round(percentage_used, 2),
        'ip': client_ip
    }


def reset_rate_limit_for_ip(ip_address, rate_type='both'):
    """
    Reset rate limit for a specific IP address.
    Useful for admin operations or testing.
    
    Args:
        ip_address: IP address to reset
        rate_type: 'hourly', 'daily', or 'both'
    
    Returns:
        bool: True if reset was successful
    """
    try:
        if rate_type in ('hourly', 'both'):
            cache_key_hourly = f'ratelimit:tryon_v2_hourly:{ip_address}'
            cache.delete(cache_key_hourly)
            logger.info("Reset hourly rate limit for IP=%s", ip_address)
        
        if rate_type in ('daily', 'both'):
            cache_key_daily = f'ratelimit:tryon_v2_daily:{ip_address}'
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

