from django.db import models
from django.core.exceptions import ValidationError
import datetime

# Create your models here.


class Job(models.Model):
    label = models.CharField(max_length=16)
    notes = models.CharField(max_length=256)
    commencement_date = models.DateField()
    suburb = models.CharField(max_length=32)
    complete = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-commencement_date']  # Order by commencement_date from newest to oldest
    
    def __str__(self):
        return self.label


class Location(models.Model):
    label = models.CharField(max_length=2)
    address = models.CharField(max_length=128, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    job = models.ForeignKey(Job, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['job', 'label'],
                name='unique_job_location_label_detector'
            )
        ]

    def __str__(self):
        return self.label


class Detector(models.Model):
    AREARAE = "AR"
    MULTIRAE = "MR"
    MINIRAE = "PP"
    MICRORAE = "MM"
    TYPE_CHOICES = [
        (AREARAE, "AreaRAE Plus"),
        (MULTIRAE, "MultiRAE"),
        (MINIRAE, "MiniRAE"),
        (MICRORAE, "MicroRAE")
    ]
    label = models.CharField(max_length=16, unique=True)
    serial = models.CharField(max_length=16, unique=True)
    detector_type = models.CharField(max_length=2, choices=TYPE_CHOICES, default=AREARAE)

    def __str__(self):
        return self.label


class Sensor(models.Model):
    GAS_CHOICES = [
        ("CO", "CO"),
        ("HS", "H2S"),
        ("LE", "LEL"),
        ("VO", "VOC"),
        ("O2", "O2")
    ]

    UNITS_CHOICES = [
        ("PPM", "ppm"),
        ("PPB", "ppb"),
        ("LEL", "%LEL"),
        ("VFV", "v/v"),
        ("MGM", "micrograms/m3")
    ]

    gas_code = models.CharField(max_length=2, choices=GAS_CHOICES, default="CO")
    units_code = models.CharField(max_length=3, choices=UNITS_CHOICES, default="PPM")
    detector = models.ForeignKey(Detector, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['gas_code', 'detector'],
                name='unique_sensor_gas_detector'
            )
        ]

    def __str__(self):
        return f'{self.gas_code} - {self.detector.label}'


class LocationSchedule(models.Model):
    location = models.ForeignKey(Location, on_delete=models.CASCADE)
    detector = models.ForeignKey(Detector, on_delete=models.CASCADE)
    start_dt = models.DateTimeField()
    stop_dt = models.DateTimeField(null=True, blank=True)

    class Meta:
        # Order by location label, then start_dt
        ordering = [
            'location__label',
            'start_dt', 
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['location', 'start_dt', 'stop_dt'],
                name='unique_location_schedule_time'
            )
        ]

    def __str__(self):
        return f"{self.detector} at {self.location} from {self.start_dt}"

    def clean(self):
        # Check for overlapping schedules at the same location (different detectors)
        overlapping_schedules = LocationSchedule.objects.filter(
            location=self.location
        ).exclude(pk=self.pk)
        
        for schedule in overlapping_schedules:
            # Check if the schedules overlap
            if self.overlaps_with(schedule):
                raise ValidationError(
                    f"Detector {self.detector} overlaps with detector {schedule.detector} "
                    f"at location {self.location} from {schedule.start_dt} to "
                    f"{schedule.stop_dt or 'present'}."
                )
        
        # Check for overlapping schedules for the same detector (different locations)
        detector_overlapping_schedules = LocationSchedule.objects.filter(
            detector=self.detector
        ).exclude(pk=self.pk)
        
        for schedule in detector_overlapping_schedules:
            # Check if the schedules overlap
            if self.overlaps_with(schedule):
                raise ValidationError(
                    f"Detector {self.detector} cannot be at two locations simultaneously. "
                    f"It is already scheduled at location {schedule.location} from "
                    f"{schedule.start_dt} to {schedule.stop_dt or 'present'}."
                )

    def overlaps_with(self, other):
        """Check if this schedule overlaps with another schedule."""
        # If either schedule is currently active (no stop time), they overlap if the start time
        # of one is before the stop time of the other
        if not self.stop_dt and not other.stop_dt:
            # Both are currently active, so they overlap
            return True
        elif not self.stop_dt:
            # Only self is currently active
            return self.start_dt < other.stop_dt if other.stop_dt else True
        elif not other.stop_dt:
            # Only other is currently active
            return other.start_dt < self.stop_dt if self.stop_dt else True
        else:
            # Both have stop times, check for overlap
            # Overlap occurs when one starts before the other ends
            return (
                (self.start_dt < other.stop_dt and other.start_dt < self.stop_dt)
            )

    def save(self, *args, **kwargs):
        # Validate before saving
        self.clean()
        super().save(*args, **kwargs)


class SensorInvalidation(models.Model):
    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE)
    start_dt = models.DateTimeField()
    stop_dt = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=256, blank=True)

    def __str__(self):
        return f"Invalid: {self.sensor} from {self.start_dt}"


class SensorReading(models.Model):
    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE)
    log_time = models.DateTimeField()
    longitude = models.FloatField(null=True)
    latitude = models.FloatField(null=True)
    status = models.CharField(max_length=64, blank=True)
    battery = models.IntegerField(null=True)
    reading = models.FloatField()
    location = models.ForeignKey(Location, null=True, on_delete=models.CASCADE)
    validation = models.ForeignKey(SensorInvalidation, null=True, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['sensor', 'log_time'],
                name='unique_sensor_log_time'
            )
        ]
        indexes = [
            models.Index(fields=['log_time']),
            models.Index(fields=['sensor', 'log_time']),
            models.Index(fields=['location', 'log_time']),
        ]

    def __str__(self):
        return f"{self.reading} {self.sensor.units_code} [{self.sensor.gas_code}] @ {self.log_time}"


# --- Utility Functions ---

def updateSensorReadingLocations():
    """Updates SensorReading location fields based on LocationSchedule."""
    # Clear all locations first
    SensorReading.objects.all().update(location=None)

    # Update locations based on schedule
    for schedule in LocationSchedule.objects.select_related('location', 'detector').all():
        # Get all sensors for this detector
        sensors = Sensor.objects.filter(detector=schedule.detector)
        
        for sensor in sensors:
            # Build the query for readings matching this sensor and time range
            reading_query = SensorReading.objects.filter(
                sensor=sensor,
                log_time__gte=schedule.start_dt
            )
            
            # If there's an end time, add that condition
            if schedule.stop_dt:
                reading_query = reading_query.filter(log_time__lte=schedule.stop_dt)
                
            # Update the location for matching readings
            updated_count = reading_query.update(location=schedule.location)
            # print(f"Updated {updated_count} readings for sensor {sensor} with location {schedule.location}")




def getDateTimeRange():
    """Returns tuple: (first_log_time, last_log_time)"""
    agg = SensorReading.objects.aggregate(
        min_time=models.Min('log_time'),
        max_time=models.Max('log_time')
    )
    return agg['min_time'], agg['max_time']


def updateValidations():
    """Updates SensorReading validation fields based on SensorInvalidation records.
    
    This utility function:
    1. Clears all validation references in sensor readings (sets validation field to null)
    2. Updates affected records by putting the foreign key of validation into the validation field
    """
    # Step 1: Clear all validation references in sensor readings
    SensorReading.objects.all().update(validation=None)
    
    # Step 2: Get all sensor invalidations
    sensor_invalidations = SensorInvalidation.objects.select_related('sensor').all()
    
    # Step 3: Update affected records with validation references
    updated_readings_count = 0
    
    for invalidation in sensor_invalidations:
        # Build the query for readings matching this sensor and time range
        reading_query = SensorReading.objects.filter(
            sensor=invalidation.sensor,
            log_time__gte=invalidation.start_dt
        )
        
        # If there's an end time, add that condition
        if invalidation.stop_dt:
            reading_query = reading_query.filter(log_time__lte=invalidation.stop_dt)
            
        # Update the validation for matching readings
        count = reading_query.update(validation=invalidation)
        updated_readings_count += count
        
        # Uncomment for debugging:
        # print(f"Updated {count} readings for sensor {invalidation.sensor} with validation {invalidation.id}")
    
    # Return the total number of updated readings
    return updated_readings_count


