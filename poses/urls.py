"""
URL Configuration for Poses App
"""

from django.urls import path
from poses.views import SceneTemplateListView, GenerateScenePoseView, GenerateScenePoseTaskStatusView

urlpatterns = [
    path('scene-templates/', SceneTemplateListView.as_view(), name='scene-template-list'),
    path('generate-scene-pose/', GenerateScenePoseView.as_view(), name='generate-scene-pose'),
    path('generate-scene-pose/<int:tryon_pose_id>/', GenerateScenePoseView.as_view(), name='generate-scene-pose-detail'),
    path('generate-scene-pose/<int:tryon_pose_id>/status', GenerateScenePoseTaskStatusView.as_view(), name='generate-scene-pose-task-status'),
]

