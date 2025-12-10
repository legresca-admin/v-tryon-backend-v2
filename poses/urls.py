"""
URL Configuration for Poses App
"""

from django.urls import path
from poses.views import SceneTemplateListView, SceneGenerationView

urlpatterns = [
    path('scene-templates/', SceneTemplateListView.as_view(), name='scene-template-list'),
    path('generate-scene-pose/', SceneGenerationView.as_view(), name='generate-scene-pose'),
]

