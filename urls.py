from django.urls import path, include
from rest_framework import routers
from . import views

router = routers.DefaultRouter()
router.register(r'jobs', views.JobViewSet)
router.register(r'detectors', views.DetectorViewSet)
router.register(r'sensor-invalidation', views.SensorInvalidationViewSet)
router.register(r'sensor-readings', views.SensorReadingViewSet)


urlpatterns = [
    path('', include(router.urls)),
    path('csrf/', views.get_csrf_token, name='api_csrf'),
    path('login/', views.api_login, name='api_login'),  # This now uses a regular Django view
    path('logout/', views.api_logout, name='api_logout'),  # This is for session logout
    path('detectors/<int:detector_id>/sensors/', views.DetectorSensorViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='detector-sensors'),
    path('detectors/<int:detector_id>/sensors/<int:pk>/', views.DetectorSensorViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='detector-sensor-detail'),
    path('jobs/<int:job_id>/locations/', views.JobLocationViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='job-locations'),
    path('jobs/<int:job_id>/locations/<int:pk>/', views.JobLocationViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='job-location-detail'),
    path('jobs/<int:job_id>/locations/<int:location_id>/schedules/', views.JobLocationScheduleViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='job-location-schedules'),
    path('jobs/<int:job_id>/locations/<int:location_id>/schedules/<int:pk>/', views.JobLocationScheduleViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='job-location-schedule-detail'),
    path('detectors/<int:detector_id>/sensors/<int:sensor_id>/sensor-readings/', views.SensorSensorReadingViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='sensor-sensor-readings'),
    path('detectors/<int:detector_id>/sensors/<int:sensor_id>/sensor-readings/<int:pk>/', views.SensorSensorReadingViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='sensor-sensor-reading-detail'),
    path('jobs/<int:job_id>/locations/<int:location_id>/sensors/<int:sensor_id>/sensor-readings/', views.JobLocationSensorReadingViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='job-location-sensor-readings'),
    path('jobs/<int:job_id>/locations/<int:location_id>/sensors/<int:sensor_id>/sensor-readings/<int:pk>/', views.JobLocationSensorReadingViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
        'delete': 'destroy'
    }), name='job-location-sensor-reading-detail'),
    path('locations/<int:location_id>/sensors/', views.JobLocationSensorViewSet.as_view({
        'get': 'list_for_location'
    }), name='location-sensors'),
    path('locations/<int:location_id>/sensors/<int:sensor_id>/sensor-readings/', views.JobLocationSensorViewSet.as_view({
        'get': 'list_sensor_readings'
    }), name='location-sensor-readings'),

    path('jobs/<int:job_id>/sensors/', views.JobSensorListView.as_view({
        'get': 'list'
    }), name='job-sensors'),
    path('csv-import/', views.CSVImportViewSet.as_view({
        'post': 'create'
    }), name='csv-import'),
    # Nested URL for location gas statistics
    path('locations/<int:location_id>/gases/<str:gas_code>/statistics/', views.JobLocationGasStatsViewSet.as_view({
        'get': 'retrieve_for_gas'
    }), name='location-gas-stats'),
    path('locations/<int:location_id>/gases/<str:gas_code>/summary/', views.JobLocationGasStatsViewSet.as_view({
        'get': 'retrieve_summary_for_gas'
    }), name='location-gas-summary'),
    path('jobs/<int:job_id>/raw-data/', views.paginated_raw_data, name='paginated-raw-data'),
    path('generate-pdf-report/', views.generate_pdf_report, name='generate_pdf_report'),
]

