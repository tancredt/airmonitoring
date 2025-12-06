import django_filters
from .models import Job, Location, Detector, Sensor, LocationSchedule, SensorInvalidation, SensorReading


class JobFilter(django_filters.FilterSet):
    label = django_filters.CharFilter(lookup_expr='icontains')
    notes = django_filters.CharFilter(lookup_expr='icontains')
    commencement_date = django_filters.DateFromToRangeFilter()
    suburb = django_filters.CharFilter(lookup_expr='icontains')
    complete = django_filters.BooleanFilter()

    class Meta:
        model = Job
        fields = ['label', 'notes', 'commencement_date', 'suburb', 'complete']


class LocationFilter(django_filters.FilterSet):
    label = django_filters.CharFilter(lookup_expr='icontains')
    address = django_filters.CharFilter(lookup_expr='icontains')
    job = django_filters.ModelChoiceFilter(queryset=Job.objects.all())

    class Meta:
        model = Location
        fields = ['label', 'address', 'job']


class DetectorFilter(django_filters.FilterSet):
    label = django_filters.CharFilter(lookup_expr='icontains')
    serial = django_filters.CharFilter(lookup_expr='icontains')
    detector_type = django_filters.ChoiceFilter(choices=Detector.TYPE_CHOICES)

    class Meta:
        model = Detector
        fields = ['label', 'serial', 'detector_type']


class SensorFilter(django_filters.FilterSet):
    gas_code = django_filters.ChoiceFilter(choices=Sensor.GAS_CHOICES)
    units_code = django_filters.ChoiceFilter(choices=Sensor.UNITS_CHOICES)
    detector = django_filters.ModelChoiceFilter(queryset=Detector.objects.all())

    class Meta:
        model = Sensor
        fields = ['gas_code', 'units_code', 'detector']


class LocationScheduleFilter(django_filters.FilterSet):
    location = django_filters.ModelChoiceFilter(queryset=Location.objects.all())
    detector = django_filters.ModelChoiceFilter(queryset=Detector.objects.all())
    start_dt = django_filters.DateTimeFromToRangeFilter()
    stop_dt = django_filters.DateTimeFromToRangeFilter()

    class Meta:
        model = LocationSchedule
        fields = ['location', 'detector', 'start_dt', 'stop_dt']


class SensorInvalidationFilter(django_filters.FilterSet):
    sensor = django_filters.ModelChoiceFilter(queryset=Sensor.objects.all())
    start_dt = django_filters.DateTimeFromToRangeFilter()
    stop_dt = django_filters.DateTimeFromToRangeFilter()
    notes = django_filters.CharFilter(lookup_expr='icontains')

    class Meta:
        model = SensorInvalidation
        fields = ['sensor', 'start_dt', 'stop_dt', 'notes']


class SensorReadingFilter(django_filters.FilterSet):
    sensor = django_filters.ModelChoiceFilter(queryset=Sensor.objects.all())
    log_time = django_filters.DateTimeFromToRangeFilter()
    longitude = django_filters.RangeFilter()
    latitude = django_filters.RangeFilter()
    status = django_filters.CharFilter(lookup_expr='icontains')
    battery = django_filters.RangeFilter()
    reading = django_filters.RangeFilter()
    location = django_filters.ModelChoiceFilter(queryset=Location.objects.all())
    validation = django_filters.ModelChoiceFilter(queryset=SensorInvalidation.objects.all())

    class Meta:
        model = SensorReading
        fields = [
            'sensor', 'log_time', 'longitude', 'latitude', 'status',
            'battery', 'reading', 'location', 'validation'
        ]
