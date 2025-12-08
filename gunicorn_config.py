"""
Gunicorn configuration file for V-Tryon Backend V2

This file configures Gunicorn for production deployment.
Adjust settings based on your server's resources and requirements.
"""

import multiprocessing
import os

# Server socket
bind = "127.0.0.1:8000"  # Listen on localhost (use Nginx as reverse proxy)
backlog = 2048

# Worker processes
# Formula: (2 x CPU cores) + 1
# Adjust based on your server's CPU count
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"  # Use 'sync' for CPU-bound, 'gevent' for I/O-bound
worker_connections = 1000  # Only used with async workers (gevent, eventlet)

# Worker timeout in seconds
# CRITICAL: Must be >= API timeout for long-running AI requests
# Set to 1000s (~16.7 minutes) to provide ample buffer for AI image generation
# NOTE: Also update Nginx proxy_read_timeout to match (at least 1000s)
timeout = 1000
keepalive = 5  # Keep-alive connections

# Logging
# Using stdout/stderr (captured by systemd/journald)
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
loglevel = "info"  # Options: debug, info, warning, error, critical

# Access log format
# %(h)s = remote address
# %(l)s = '-'
# %(u)s = user name
# %(t)s = date of the request
# %(r)s = status line (e.g. GET / HTTP/1.1)
# %(s)s = status
# %(b)s = response length or '-'
# %(f)s = referer
# %(a)s = user agent
# %(D)s = request duration in microseconds
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "v-tryon-backend-v2"

# Server mechanics
daemon = False  # Don't daemonize (systemd will handle this)
pidfile = None  # Let systemd manage the PID
umask = 0o007  # Restrict file permissions

# Preload app for better performance (use with caution)
preload_app = False

# Graceful timeout for worker shutdown
graceful_timeout = 30

# Maximum requests per worker before restart (helps prevent memory leaks)
max_requests = 1000
max_requests_jitter = 50

