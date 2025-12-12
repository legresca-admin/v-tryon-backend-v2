"""
URL Configuration for Try-On App
"""

from django.urls import path
from .views import tryon_v2, tryon_task_status, tryon_list, tryon_detail

urlpatterns = [
    path('v2/tryon', tryon_v2, name='tryon-v2'),
    path('v2/tryon/<int:tryon_request_id>/status', tryon_task_status, name='tryon-task-status'),
    path('v2/tryon/list', tryon_list, name='tryon-list'),
    path('v2/tryon/<int:tryon_request_id>', tryon_detail, name='tryon-detail'),
]

