"""
Management command to manage rate limits for the try-on API.

Usage:
    python manage.py ratelimit status <ip_address>     # Check rate limit status
    python manage.py ratelimit reset <ip_address>       # Reset rate limit for IP
    python manage.py ratelimit reset --all              # Reset all rate limits
"""

from django.core.management.base import BaseCommand, CommandError
from django.core.cache import cache
from tryon.utils import get_rate_limit_status, reset_rate_limit_for_ip
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Manage rate limits for the try-on API'

    def add_arguments(self, parser):
        parser.add_argument(
            'action',
            type=str,
            choices=['status', 'reset'],
            help='Action to perform: status or reset'
        )
        parser.add_argument(
            'ip_address',
            type=str,
            nargs='?',
            help='IP address to check/reset (optional for reset --all)'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Reset all rate limits (only for reset action)'
        )

    def handle(self, *args, **options):
        action = options['action']
        ip_address = options.get('ip_address')
        reset_all = options.get('all', False)

        if action == 'status':
            if not ip_address:
                raise CommandError('IP address is required for status action')
            
            # Create a mock request object for get_rate_limit_status
            from django.test import RequestFactory
            factory = RequestFactory()
            request = factory.post('/v2/tryon')
            request.META['REMOTE_ADDR'] = ip_address
            
            hourly_status = get_rate_limit_status(request, 'hourly')
            daily_status = get_rate_limit_status(request, 'daily')
            
            self.stdout.write(self.style.SUCCESS(f'\nRate Limit Status for IP: {ip_address}'))
            self.stdout.write('=' * 60)
            self.stdout.write(f'Hourly Limit: {hourly_status["current_count"]}/{hourly_status["limit"]} ({hourly_status["percentage_used"]}% used)')
            self.stdout.write(f'  Remaining: {hourly_status["remaining"]} requests')
            self.stdout.write(f'\nDaily Limit: {daily_status["current_count"]}/{daily_status["limit"]} ({daily_status["percentage_used"]}% used)')
            self.stdout.write(f'  Remaining: {daily_status["remaining"]} requests')
            self.stdout.write('=' * 60)
            
        elif action == 'reset':
            if reset_all:
                # Clear all rate limit cache keys
                # Note: This is a simple approach - in production you might want to track keys
                self.stdout.write(self.style.WARNING('Resetting all rate limits...'))
                # Since we're using LocMemCache, we can't easily list all keys
                # This would require a more sophisticated cache backend
                self.stdout.write(self.style.ERROR('Cannot reset all with LocMemCache. Use Redis or Memcached for this feature.'))
                self.stdout.write('To reset specific IPs, use: python manage.py ratelimit reset <ip_address>')
            elif ip_address:
                if reset_rate_limit_for_ip(ip_address, 'both'):
                    self.stdout.write(self.style.SUCCESS(f'Successfully reset rate limits for IP: {ip_address}'))
                else:
                    self.stdout.write(self.style.ERROR(f'Failed to reset rate limits for IP: {ip_address}'))
            else:
                raise CommandError('IP address is required for reset action (or use --all flag)')

