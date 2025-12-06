from rest_framework import viewsets, permissions
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.pagination import PageNumberPagination
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.core.exceptions import ValidationError
from django.db.models import Avg, Min, Max, Count, Q
from django.utils import timezone
from django.conf import settings
import datetime
import csv
import io
import re
from datetime import datetime, timedelta
from .models import Job, Location, Detector, Sensor, LocationSchedule, SensorInvalidation, SensorReading
from .serializers import (
    JobSerializer, LocationSerializer, DetectorSerializer, SensorSerializer,
    LocationScheduleSerializer, SensorInvalidationSerializer, SensorReadingSerializer,
    SensorWithDetectorSerializer, PaginatedSensorReadingSerializer
)
from .filters import (
    JobFilter, LocationFilter, DetectorFilter, SensorFilter,
    LocationScheduleFilter, SensorInvalidationFilter, SensorReadingFilter
)
from .reports import getReport


class JobViewSet(viewsets.ModelViewSet):
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    # filterset_class = JobFilter  # Filter commented out
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]


class JobLocationViewSet(viewsets.ModelViewSet):
    serializer_class = LocationSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        job_id = self.kwargs['job_id']
        return Location.objects.filter(job_id=job_id)
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['job_id'] = self.kwargs.get('job_id')
        return context
    
    def perform_create(self, serializer):
        job_id = self.kwargs['job_id']
        job = get_object_or_404(Job, id=job_id)
        serializer.save(job=job)


class DetectorViewSet(viewsets.ModelViewSet):
    queryset = Detector.objects.all()
    serializer_class = DetectorSerializer
    # filterset_class = DetectorFilter  # Filter commented out
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]


class DetectorSensorViewSet(viewsets.ModelViewSet):
    serializer_class = SensorSerializer
    authentication_classes = [SessionAuthenticationn]
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        detector_id = self.kwargs['detector_id']
        return Sensor.objects.filter(detector_id=detector_id)
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['detector_id'] = self.kwargs.get('detector_id')
        return context
    
    def perform_create(self, serializer):
        detector_id = self.kwargs['detector_id']
        detector = get_object_or_404(Detector, id=detector_id)
        serializer.save(detector=detector)


class SensorInvalidationViewSet(viewsets.ModelViewSet):
    queryset = SensorInvalidation.objects.all()
    serializer_class = SensorInvalidationSerializer
    # filterset_class = SensorInvalidationFilter  # Filter commented out
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]


class CSVImportViewSet(viewsets.ViewSet):
    """
    ViewSet for importing CSV files containing sensor data.
    """
    parser_classes = (MultiPartParser, FormParser)
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def create(self, request):
        """
        Handle CSV file upload and import the data.
        """
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
            
        if not file_obj.name.endswith('.csv'):
            return Response({'error': 'File must be a CSV'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Process the CSV file
            created_detectors, created_sensors, created_readings = self.process_csv(file_obj)
            
            return Response({
                'message': 'CSV import successful',
                'statistics': {
                    'detectors_created': created_detectors,
                    'sensors_created': created_sensors,
                    'readings_created': created_readings
                }
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class SensorReadingViewSet(viewsets.ModelViewSet):
    queryset = SensorReading.objects.all()
    serializer_class = SensorReadingSerializer
    # filterset_class = SensorReadingFilter  # Filter commented out
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]


class JobLocationScheduleViewSet(viewsets.ModelViewSet):
    serializer_class = LocationScheduleSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        job_id = self.kwargs['job_id']
        location_id = self.kwargs['location_id']
        return LocationSchedule.objects.filter(
            location__job_id=job_id, 
            location_id=location_id
        ).select_related('location')
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['job_id'] = self.kwargs.get('job_id')
        context['location_id'] = self.kwargs.get('location_id')
        return context
    
    def perform_create(self, serializer):
        job_id = self.kwargs['job_id']
        location_id = self.kwargs['location_id']
        # Get the location object to associate with the schedule
        location = get_object_or_404(Location, id=location_id, job_id=job_id)
        serializer.save(location=location)


class SensorSensorReadingViewSet(viewsets.ModelViewSet):
    serializer_class = SensorReadingSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        detector_id = self.kwargs['detector_id']
        sensor_id = self.kwargs['sensor_id']
        return SensorReading.objects.filter(
            sensor__detector_id=detector_id,
            sensor_id=sensor_id,
            validation__isnull=True
        ).select_related('sensor', 'location')
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['detector_id'] = self.kwargs.get('detector_id')
        context['sensor_id'] = self.kwargs.get('sensor_id')
        return context
    
    def perform_create(self, serializer):
        detector_id = self.kwargs['detector_id']
        sensor_id = self.kwargs['sensor_id']
        # Get the sensor object to associate with the reading
        sensor = get_object_or_404(Sensor, id=sensor_id, detector_id=detector_id)
        serializer.save(sensor=sensor)


class JobLocationSensorReadingViewSet(viewsets.ModelViewSet):
    serializer_class = SensorReadingSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        job_id = self.kwargs['job_id']
        location_id = self.kwargs['location_id']
        sensor_id = self.kwargs['sensor_id']
        # Ensure location belongs to the job
        location = get_object_or_404(Location, id=location_id, job_id=job_id)
        # Filter readings by the specific sensor and location
        # Only include sensor readings where validation is null (i.e., valid readings)
        return SensorReading.objects.filter(
            sensor_id=sensor_id,
            location=location,
            validation__isnull=True
        ).select_related('sensor', 'location')
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['job_id'] = self.kwargs.get('job_id')
        context['location_id'] = self.kwargs.get('location_id')
        context['sensor_id'] = self.kwargs.get('sensor_id')
        return context
    
    def perform_create(self, serializer):
        job_id = self.kwargs['job_id']
        location_id = self.kwargs['location_id']
        sensor_id = self.kwargs['sensor_id']
        # Get the location and sensor objects to validate they exist and are properly connected
        location = get_object_or_404(Location, id=location_id, job_id=job_id)
        sensor = get_object_or_404(Sensor, id=sensor_id)
        # Set location and sensor for the new reading
        serializer.save(location=location, sensor=sensor)


class JobSensorListView(viewsets.ViewSet):
    """
    ViewSet for retrieving sensors used in a specific job.
    Returns unique sensors from detectors that have been scheduled at locations in the job.
    """
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def list(self, request, job_id=None):
        """
        Get all unique sensors used in a job.
        Sensors are from detectors that have been scheduled at locations in this job.
        """
        try:
            # Get the job to ensure it exists
            job = get_object_or_404(Job, id=job_id)
            
            # Get all location schedules for this job to find detectors used
            location_schedules = LocationSchedule.objects.filter(
                location__job_id=job_id
            ).select_related('detector', 'location')
            
            # Get unique detector IDs from schedules
            detector_ids = location_schedules.values_list('detector_id', flat=True).distinct()
            
            # Get sensors for these detectors
            sensors = Sensor.objects.filter(detector_id__in=detector_ids).select_related('detector')
            
            # Serialize the sensors with detector information
            serializer = SensorWithDetectorSerializer(sensors, many=True)
            return Response(serializer.data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)




class JobLocationSensorViewSet(viewsets.ViewSet):
    """
    ViewSet for retrieving sensors used in a specific location within a job.
    Returns sensors from detectors that have been scheduled at the specified location.
    """
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def list_for_location(self, request, job_id=None, location_id=None):
        """
        Get all sensors associated with a specific location in a job.
        Returns sensors from detectors that have been scheduled at this location.
        """
        try:
            # Ensure the job and location exist and are related
            job = get_object_or_404(Job, id=job_id)
            location = get_object_or_404(Location, id=location_id, job_id=job_id)
            
            # Get all detectors that have been scheduled at this location
            detector_schedules = LocationSchedule.objects.filter(location=location)
            
            # Get unique detector IDs from schedules
            detector_ids = detector_schedules.values_list('detector_id', flat=True).distinct()
            
            # Get all sensors for these detectors
            sensors = Sensor.objects.filter(detector_id__in=detector_ids).select_related('detector')
            
            # Serialize the sensors with detector information
            serializer = SensorWithDetectorSerializer(sensors, many=True)
            return Response(serializer.data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    def list_sensor_readings(self, request, job_id=None, location_id=None, sensor_id=None):
        """
        Get all sensor readings for a specific sensor at a specific location within a job.
        Supports pagination and filtering.
        Returns sensor readings filtered by job, location, and sensor.
        """
        try:
            # Ensure the job, location, and sensor exist and are properly related
            job = get_object_or_404(Job, id=job_id)
            location = get_object_or_404(Location, id=location_id, job_id=job_id)
            sensor = get_object_or_404(Sensor, id=sensor_id)
            
            # Verify that this sensor belongs to a detector that has been scheduled at this location
            detector_schedules = LocationSchedule.objects.filter(
                location=location,
                detector=sensor.detector
            )
            
            if not detector_schedules.exists():
                return Response({
                    'error': f'Sensor {sensor_id} is not associated with any detector scheduled at location {location_id}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get the base queryset for sensor readings
            # Only include sensor readings where validation is null (i.e., valid readings)
            queryset = SensorReading.objects.filter(
                sensor=sensor,
                location=location,
                validation__isnull=True
            ).select_related('sensor', 'location', 'validation').order_by('log_time')
            
            # Apply limit if requested
            limit = request.query_params.get('limit')
            if limit:
                try:
                    limit = int(limit)
                    # Slice the queryset before evaluating it
                    queryset = queryset[:limit]
                except (ValueError, TypeError):
                    pass  # Ignore invalid limit parameter
            
            # Convert to list to evaluate the queryset with slicing
            readings_list = list(queryset)
            
            # Serialize the sensor readings
            serializer = SensorReadingSerializer(readings_list, many=True)
            return Response(serializer.data)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class JobLocationGasStatsViewSet(viewsets.ViewSet):
    """
    ViewSet for retrieving time series statistics for gas readings at specific job locations.
    Provides aggregated data (average, min, max, count) for a specific gas over time intervals.
    URL: /api/jobs/{job_id}/locations/{location_id}/gases/{gas_code}/
    """
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def retrieve_for_gas(self, request, job_id=None, location_id=None, gas_code=None):
        """
        Get aggregated statistics for a specific gas at a specific location within a job.
        URL: /api/jobs/{job_id}/locations/{location_id}/gases/{gas_code}/statistics/
        Query parameters:
        - start_date: Start datetime (format: YYYY-MM-DDTHH:MM:SS)
        - end_date: End datetime (format: YYYY-MM-DDTHH:MM:SS)
        - interval: Time interval in minutes (default: 60)
        """
        try:
            # Parse query parameters
            start_date_str = request.query_params.get('start_date')
            end_date_str = request.query_params.get('end_date')
            interval_minutes = int(request.query_params.get('interval', 60))  # Default to 60 minutes
            
            if not start_date_str or not end_date_str:
                return Response({
                    'error': 'start_date and end_date parameters are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Parse datetime strings with strict format: YYYYMMDDTHHMM
            try:
                # Parse the specific format: YYYYMMDDTHHMM
                if len(start_date_str) == 13 and start_date_str[8] == 'T':
                    year = int(start_date_str[0:4])
                    month = int(start_date_str[4:6])
                    day = int(start_date_str[6:8])
                    hour = int(start_date_str[9:11])
                    minute = int(start_date_str[11:13])
                    start_date = datetime(year, month, day, hour, minute)
                else:
                    raise ValueError("Invalid date format")
                    
                if len(end_date_str) == 13 and end_date_str[8] == 'T':
                    year = int(end_date_str[0:4])
                    month = int(end_date_str[4:6])
                    day = int(end_date_str[6:8])
                    hour = int(end_date_str[9:11])
                    minute = int(end_date_str[11:13])
                    end_date = datetime(year, month, day, hour, minute)
                else:
                    raise ValueError("Invalid date format")
            except ValueError:
                return Response({
                    'error': 'Invalid datetime format. Use format: YYYYMMDDTHHMM (e.g., 20230101T1000)'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate that job and location exist and are related
            try:
                job = get_object_or_404(Job, id=job_id)
                location = get_object_or_404(Location, id=location_id, job_id=job_id)
            except Exception:
                return Response({
                    'error': 'Job or location not found or not associated with each other'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate gas code against allowed choices
            gas_codes = [choice[0] for choice in Sensor.GAS_CHOICES]
            if gas_code not in gas_codes:
                return Response({
                    'error': f'Invalid gas code: {gas_code}. Must be one of: {gas_codes}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Build the queryset with filters for the specific job, location, and gas
            # Only include sensor readings where validation is null (i.e., valid readings)
            queryset = SensorReading.objects.filter(
                location_id=location_id,
                sensor__gas_code=gas_code,
                validation__isnull=True
            ).select_related('sensor', 'location')
            
            # Filter by date range
            queryset = queryset.filter(
                log_time__gte=start_date,
                log_time__lte=end_date
            )
            
            # Calculate time intervals and group readings
            interval_timedelta = timedelta(minutes=interval_minutes)
            current_time = start_date
            
            results = []
            
            while current_time < end_date:
                interval_end = current_time + interval_timedelta
                if interval_end > end_date:
                    interval_end = end_date
                
                # Get readings for this interval
                # Using log_time > current_time and log_time <= interval_end
                # This creates intervals (current_time, interval_end]
                interval_readings = queryset.filter(
                    log_time__gt=current_time,
                    log_time__lte=interval_end
                )
                
                # Calculate statistics for this interval
                stats = interval_readings.aggregate(
                    avg_reading=Avg('reading'),
                    min_reading=Min('reading'),
                    max_reading=Max('reading'),
                    count_readings=Count('id')
                )
                
                # Add interval info to the result
                results.append({
                    'interval_start': current_time.isoformat(),
                    'interval_end': interval_end.isoformat(),
                    'avg': stats['avg_reading'],
                    'min': stats['min_reading'],
                    'max': stats['max_reading'],
                    'count': stats['count_readings']
                })
                
                current_time = interval_end
            
            return Response(results)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def retrieve_summary_for_gas(self, request, job_id=None, location_id=None, gas_code=None):
        """
        Get summary statistics for a specific gas at a specific location within a job.
        URL: /api/jobs/{job_id}/locations/{location_id}/gases/{gas_code}/summary/
        Query parameters:
        - start_date: Start datetime (format: YYYYMMDDTHHMM)
        - end_date: End datetime (format: YYYYMMDDTHHMM)
        - interval: Time interval in minutes (default: 60)
        
        Returns:
        - average: Overall average reading for the time range
        - count: Total count of readings in the time range
        - max_avg: Maximum of the average readings for the intervals in the time range
        - min_avg: Minimum of the average readings for the intervals in the time range
        - max_individual: Maximum individual reading in the time range
        - min_individual: Minimum individual reading in the time range
        """
        try:
            # Parse query parameters
            start_date_str = request.query_params.get('start_date')
            end_date_str = request.query_params.get('end_date')
            interval_minutes = int(request.query_params.get('interval', 60))  # Default to 60 minutes
            
            if not start_date_str or not end_date_str:
                return Response({
                    'error': 'start_date and end_date parameters are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Parse datetime strings with strict format: YYYYMMDDTHHMM
            try:
                # Parse the specific format: YYYYMMDDTHHMM
                if len(start_date_str) == 13 and start_date_str[8] == 'T':
                    year = int(start_date_str[0:4])
                    month = int(start_date_str[4:6])
                    day = int(start_date_str[6:8])
                    hour = int(start_date_str[9:11])
                    minute = int(start_date_str[11:13])
                    start_date = datetime(year, month, day, hour, minute)
                else:
                    raise ValueError("Invalid date format")
                    
                if len(end_date_str) == 13 and end_date_str[8] == 'T':
                    year = int(end_date_str[0:4])
                    month = int(end_date_str[4:6])
                    day = int(end_date_str[6:8])
                    hour = int(end_date_str[9:11])
                    minute = int(end_date_str[11:13])
                    end_date = datetime(year, month, day, hour, minute)
                else:
                    raise ValueError("Invalid date format")
            except (ValueError, IndexError):
                return Response({
                    'error': 'Invalid datetime format. Use format: YYYYMMDDTHHMM (e.g., 20230101T1000)'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate gas code against allowed choices
            gas_codes = [choice[0] for choice in Sensor.GAS_CHOICES]
            if gas_code not in gas_codes:
                return Response({
                    'error': f'Invalid gas code: {gas_code}. Must be one of: {gas_codes}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Build the queryset with filters for the specific job, location, and gas
            # Only include sensor readings where validation is null (i.e., valid readings)
            queryset = SensorReading.objects.filter(
                location_id=location_id,
                sensor__gas_code=gas_code,
                validation__isnull=True
            ).select_related('sensor', 'location')
            
            # Filter by date range
            queryset = queryset.filter(
                log_time__gte=start_date,
                log_time__lte=end_date
            )
            
            # Calculate overall statistics for the time range
            overall_stats = queryset.aggregate(
                avg_reading=Avg('reading'),
                count_readings=Count('id'),
                max_individual=Max('reading'),
                min_individual=Min('reading')
            )
            
            # Calculate time intervals and group readings for interval-based stats
            interval_timedelta = timedelta(minutes=interval_minutes)
            current_time = start_date
            
            interval_averages = []
            
            while current_time < end_date:
                interval_end = current_time + interval_timedelta
                if interval_end > end_date:
                    interval_end = end_date
                
                # Get readings for this interval
                # Using log_time > current_time and log_time <= interval_end
                # This creates intervals (current_time, interval_end]
                interval_readings = queryset.filter(
                    log_time__gt=current_time,
                    log_time__lte=interval_end
                )
                
                # Calculate average for this interval
                interval_avg = interval_readings.aggregate(avg_reading=Avg('reading'))
                
                if interval_avg['avg_reading'] is not None:
                    interval_averages.append(interval_avg['avg_reading'])
                
                current_time = interval_end
            
            # Calculate min/max of interval averages
            max_avg = None
            min_avg = None
            if interval_averages:
                max_avg = max(interval_averages)
                min_avg = min(interval_averages)
            
            # Prepare the response
            result = {
                'average': overall_stats['avg_reading'],
                'count': overall_stats['count_readings'],
                'max_avg': max_avg,
                'min_avg': min_avg,
                'max_individual': overall_stats['max_individual'],
                'min_individual': overall_stats['min_individual']
            }
            
            return Response(result)
            
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# Custom pagination class for raw data


class RawDataPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 1000


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def paginated_raw_data(request, job_id=None):
    """
    Paginated endpoint to fetch raw sensor readings for a specific job,
    filtered by locations and gases specified as query parameters.
    """
    try:
        # Get the job to ensure it exists
        job = get_object_or_404(Job, id=job_id)
        
        # Get query parameters for filtering
        location_ids = request.query_params.getlist('location_ids')
        gas_codes = request.query_params.getlist('gas_codes')
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')
        
        # Build the queryset with base job filter
        queryset = SensorReading.objects.filter(
            location__job_id=job_id,
        ).select_related('sensor', 'location', 'validation').order_by('log_time')
        
        # Apply location filters if specified
        if location_ids:
            # Convert string IDs to integers and filter
            location_ids_int = [int(id) for id in location_ids if id.isdigit()]
            if location_ids_int:
                queryset = queryset.filter(location_id__in=location_ids_int)
        
        # Apply gas code filters if specified
        if gas_codes:
            queryset = queryset.filter(sensor__gas_code__in=gas_codes)
        
        # Apply date range filters if specified
        if start_date_str:
            try:
                # Parse the specific format: YYYYMMDDTHHMM
                if len(start_date_str) == 13 and start_date_str[8] == 'T':
                    year = int(start_date_str[0:4])
                    month = int(start_date_str[4:6])
                    day = int(start_date_str[6:8])
                    hour = int(start_date_str[9:11])
                    minute = int(start_date_str[11:13])
                    start_date = datetime(year, month, day, hour, minute)
                    queryset = queryset.filter(log_time__gte=start_date)
                else:
                    raise ValueError("Invalid date format")
            except (ValueError, IndexError):
                return Response(
                    {'error': 'Invalid start date format. Use format: YYYYMMDDTHHMM (e.g., 20230101T1000).'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        if end_date_str:
            try:
                # Parse the specific format: YYYYMMDDTHHMM
                if len(end_date_str) == 13 and end_date_str[8] == 'T':
                    year = int(end_date_str[0:4])
                    month = int(end_date_str[4:6])
                    day = int(end_date_str[6:8])
                    hour = int(end_date_str[9:11])
                    minute = int(end_date_str[11:13])
                    end_date = datetime(year, month, day, hour, minute)
                    queryset = queryset.filter(log_time__lte=end_date)
                else:
                    raise ValueError("Invalid date format")
            except (ValueError, IndexError):
                return Response(
                    {'error': 'Invalid end date format. Use format: YYYYMMDDTHHMM (e.g., 20230101T1000).'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Include all sensor readings (both valid and invalid)
        # queryset = queryset.filter(validation__isnull=True)  # Commented out to return all data
        
        # Apply pagination
        paginator = RawDataPagination()
        paginated_queryset = paginator.paginate_queryset(queryset, request)
        
        # Serialize the paginated results
        serializer = PaginatedSensorReadingSerializer(paginated_queryset, many=True)
        
        # Return paginated response
        return paginator.get_paginated_response(serializer.data)
        
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def logout_view(request):
    """
    Logout endpoint that deletes the user's authentication token.
    """
    try:
        # Get the user's token
        token = Token.objects.get(user=request.user)
        # Delete the token
        token.delete()
        return Response({'message': 'Successfully logged out'}, status=status.HTTP_200_OK)
    except Token.DoesNotExist:
        # Token doesn't exist, but we can still return success
        return Response({'message': 'Successfully logged out'}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def generate_pdf_report(request):
    """
    Generate a PDF report based on user selections from the reports store.
    """
    try:
        # Get the request data
        request_data = request.data
        print(f"Received request data: {request_data}")
        
        # Create data for the report
        report_data = {
            'selected_job': request_data.get('selected_job'),
            'report_options': request_data.get('report_options', {}),
            'start_date': request_data.get('start_date'),
            'end_date': request_data.get('end_date'),
            'selected_locations': request_data.get('selected_locations', []),
            'selected_gases': request_data.get('selected_gases', [])
        }
        
        print(f"Processed report data: {report_data}")
        
        # Generate the PDF using the reports module
        pdf_buffer = getReport(report_data)
        
        # Create the HTTP response with PDF content
        response = HttpResponse(
            pdf_buffer.getvalue(),
            content_type='application/pdf'
        )
        response['Content-Disposition'] = f'attachment; filename="report_job_{report_data["selected_job"] if report_data["selected_job"] else "unknown"}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        
        return response
        
    except Exception as e:
        import traceback
        print(f"Error in generate_pdf_report: {str(e)}")
        print(traceback.format_exc())
        return Response(
            {'error': str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
  


