from django.db import models

# Create your models here.

class Job(models.Model):
  label = models.CharField(max_length=16)
  notes = models.CharField(max_length=256)
  commencement_date = models.DateField()
  suburb = models.CharField(max_length=32)
  complete = models.BooleanField(default=False)
    
  class Meta:
    ordering = ['-commencement_date']  

  def __str__(self):
    return self.label
