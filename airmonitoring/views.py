from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication

from .models import (
  Job
)
from .serializers import (
  JobSerializer
)

class JobViewSet(viewsets.ModelViewSet):
  queryset = Job.objects.all()
  serializer_class = JobSerializer
  authentication_classes = [SessionAuthentication]
  permission_classes = [permissions.IsAuthenticated]

    


