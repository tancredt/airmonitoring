from django.urls import path, include
from . import views

urlpatterns = [
  path('jobs/', views.JobViewSet, name='jobs'),
]
