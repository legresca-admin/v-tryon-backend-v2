"""
URL Configuration for Version Control App
"""

from django.urls import path
from .views import current_version

urlpatterns = [
    path('v2/current-version', current_version, name='current-version'),
]

