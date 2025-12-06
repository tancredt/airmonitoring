from rest_framework import serializers
from .models import Job, Location, Detector, Sensor, LocationSchedule, SensorInvalidation, SensorReading


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = '__all__'


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = '__all__'
    

    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If we have a job_id in the context, we make the job field read-only
        # since it will be set by the view
        if 'context' in kwargs and 'job_id' in kwargs['context']:
            self.fields['job'].read_only = True


class DetectorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Detector
        fields = '__all__'


class SensorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sensor
        fields = '__all__'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If we have detector_id in the context, we make the detector field read-only
        # since it will be set by the view based on the URL parameters
        if 'context' in kwargs and 'detector_id' in kwargs['context']:
            self.fields['detector'].read_only = True
        else:
            # For standalone access (if needed later), include all detectors
            self.fields['detector'] = serializers.PrimaryKeyRelatedField(queryset=Detector.objects.all())


class LocationScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocationSchedule
        fields = '__all__'
    

    
    def validate(self, data):
        """
        Custom validation for LocationSchedule to provide descriptive error messages
        """
        start_dt = data.get('start_dt')
        stop_dt = data.get('stop_dt')
        location = data.get('location')
        detector = data.get('detector')
        
        # Validate start_dt and stop_dt relationship
        if start_dt and stop_dt and start_dt > stop_dt:
            raise serializers.ValidationError({
                'start_dt': 'Start datetime must be before stop datetime.',
                'stop_dt': 'Stop datetime must be after start datetime.'
            })
        
        # Create a temporary instance to use the model's overlap checking
        # We'll copy the data to check for overlaps
        temp_instance = LocationSchedule(
            location=location,
            detector=detector,
            start_dt=start_dt,
            stop_dt=stop_dt
        )
        
        # Temporarily assign the instance's primary key for exclusion in overlap check
        if self.instance:
            temp_instance.pk = self.instance.pk
        
        # Check for overlapping schedules at the same location (different detectors)
        if location:
            overlapping_schedules = LocationSchedule.objects.filter(
                location=location
            ).exclude(pk=temp_instance.pk if temp_instance.pk else None)
            
            for schedule in overlapping_schedules:
                if temp_instance.overlaps_with(schedule):
                    raise serializers.ValidationError({
                        'non_field_errors': [
                            f'Detector {detector} overlaps with detector {schedule.detector} '
                            f'at location {location} from {schedule.start_dt} to '
                            f'{schedule.stop_dt or "present"}.'
                        ]
                    })
        
        # Check for overlapping schedules for the same detector (different locations)
        if detector:
            detector_overlapping_schedules = LocationSchedule.objects.filter(
                detector=detector
            ).exclude(pk=temp_instance.pk if temp_instance.pk else None)
            
            for schedule in detector_overlapping_schedules:
                if temp_instance.overlaps_with(schedule):
                    raise serializers.ValidationError({
                        'detector': [
                            f'Detector {detector} cannot be at two locations simultaneously. '
                            f'It is already scheduled at location {schedule.location} from '
                            f'{schedule.start_dt} to {schedule.stop_dt or "present"}.'
                        ]
                    })
        
        return data
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If we have both job_id and location_id in the context, make location field read-only
        # since it will be enforced by the view
        if ('context' in kwargs and 
            'job_id' in kwargs['context'] and 
            'location_id' in kwargs['context']):
            self.fields['location'].read_only = True
        # If we only have job_id in the context, filter locations to that job
        elif 'context' in kwargs and 'job_id' in kwargs['context']:
            job_id = kwargs['context']['job_id']
            self.fields['location'] = serializers.PrimaryKeyRelatedField(
                queryset=Location.objects.filter(job_id=job_id)
            )
        # Otherwise, allow all locations (for standalone use if needed)
        else:
            self.fields['location'] = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all())
        
        # Detectors are not restricted by job/location in the model, so allow all
        self.fields['detector'] = serializers.PrimaryKeyRelatedField(queryset=Detector.objects.all())


class SensorReadingSerializer(serializers.ModelSerializer):
    sensor = serializers.PrimaryKeyRelatedField(queryset=Sensor.objects.all())
    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all(), required=False, allow_null=True)
    validation = serializers.PrimaryKeyRelatedField(queryset=SensorInvalidation.objects.all(), required=False, allow_null=True)
    
    class Meta:
        model = SensorReading
        fields = '__all__'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If we have both detector_id and sensor_id in the context, make sensor field read-only
        # since it will be enforced by the view
        if ('context' in kwargs and 
            'detector_id' in kwargs['context'] and 
            'sensor_id' in kwargs['context']):
            self.fields['sensor'].read_only = True
        # If we only have detector_id in the context, filter sensors to that detector
        elif 'context' in kwargs and 'detector_id' in kwargs['context']:
            detector_id = kwargs['context']['detector_id']
            self.fields['sensor'] = serializers.PrimaryKeyRelatedField(
                queryset=Sensor.objects.filter(detector_id=detector_id)
            )
        # Otherwise, allow all sensors (for standalone use if needed)
        else:
            self.fields['sensor'] = serializers.PrimaryKeyRelatedField(queryset=Sensor.objects.all())
        
        # Keep the other fields as they are
        self.fields['location'] = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all(), required=False, allow_null=True)
        self.fields['validation'] = serializers.PrimaryKeyRelatedField(queryset=SensorInvalidation.objects.all(), required=False, allow_null=True)


class SensorWithDetectorSerializer(serializers.ModelSerializer):
    """
    Serializer that includes both sensor information and its parent detector information
    """
    detector_info = DetectorSerializer(source='detector', read_only=True)
    
    class Meta:
        model = Sensor
        fields = ['id', 'gas_code', 'units_code', 'detector', 'detector_info']


class SensorInvalidationSerializer(serializers.ModelSerializer):
    sensor = serializers.PrimaryKeyRelatedField(queryset=Sensor.objects.all())
    sensor_info = SensorWithDetectorSerializer(source='sensor', read_only=True)
    
    class Meta:
        model = SensorInvalidation
        fields = '__all__'


class PaginatedSensorReadingSerializer(serializers.ModelSerializer):
    """
    Serializer for paginated raw data that includes only necessary gas information
    """
    # Add specific gas information fields directly
    gas_code = serializers.CharField(source='sensor.gas_code', read_only=True)
    units_code = serializers.CharField(source='sensor.units_code', read_only=True)
    
    class Meta:
        model = SensorReading
        fields = '__all__'  # Include all original fields plus the new ones
