from django.urls import path, include
from . import views

urlpatterns = [
  path('jobs/', views.JobViewSet.as_view({'get': 'list', 'put': 'update', 'post': 'create'), name='jobs'),
]
