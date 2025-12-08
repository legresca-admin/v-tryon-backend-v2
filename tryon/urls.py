"""
URL Configuration for Try-On App
"""

from django.urls import path
from .views import tryon_v2

urlpatterns = [
    path('v2/tryon', tryon_v2, name='tryon-v2'),
]

