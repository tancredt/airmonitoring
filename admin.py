from django.contrib import admin
from django.core.exceptions import ValidationError
from .models import Detector, Sensor, Location, Job, LocationSchedule, SensorInvalidation, SensorReading

# Register your models here.
class LocationScheduleAdmin(admin.ModelAdmin):
    list_display = ('location', 'detector', 'start_dt', 'stop_dt')
    list_filter = ('location', 'detector')
    search_fields = ('location__label', 'detector__label')
    
    def save_model(self, request, obj, form, change):
        try:
            obj.save()
        except ValidationError as e:
            form.add_error(None, e.message)
        else:
            super().save_model(request, obj, form, change)

admin.site.register(Job)
admin.site.register(Location)
admin.site.register(Detector)
admin.site.register(Sensor)
admin.site.register(LocationSchedule, LocationScheduleAdmin)
admin.site.register(SensorInvalidation)
admin.site.register(SensorReading)
