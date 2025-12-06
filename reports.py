import os
import datetime
import io
import numpy as np
from PIL import Image

#for pdf
from django.conf import settings
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import cm
from reportlab.lib.pagesizes import A4

#for charts
import matplotlib
#need to use agg to prevent thread error
matplotlib.use('agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.dates as mdates

#for map
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.io.img_tiles import OSM

# for database models
from .models import Job, Location, SensorReading, Sensor
from django.db.models import Avg, Min, Max, Count, Q
from django.db.models.functions import Trunc

# for data structures and utilities
from collections import defaultdict
from datetime import timedelta
import math

# Gas code to display name mapping (moved outside function for module-level access)
def get_gas_display_name(gas_code):
    gas_mapping = {
        'CO': 'CO',
        'HS': 'H2S', 
        'LE': 'LEL',
        'VO': 'VOC',
        'O2': 'O2'
    }
    return gas_mapping.get(gas_code, gas_code)  # Return original if not found

def set_x_axis_format(ax, start_date, end_date):
    """
    Consistent x-axis formatting for charts
    """
    # Determine appropriate tick intervals based on the time range
    time_delta = end_date - start_date
    total_hours = time_delta.total_seconds() / 3600  # Convert to hours
    
    if total_hours <= 12:  # Less than 12 hours: show every hour
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_minor_locator(mdates.MinuteLocator(interval=15))  # Minor ticks every 15 minutes
    elif total_hours <= 48:  # Less than 2 days: show every 2 hours
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
    elif total_hours <= 168:  # Less than 7 days: show every 6 hours
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
    elif total_hours <= 720:  # Less than 30 days: show daily
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    else:  # More than 30 days: show monthly
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    
    plt.xticks(rotation=45)

def calculate_grouped_bar_positions_and_widths(time_interval_minutes, total_elements_in_group, max_elements_in_any_group, total_time_points):
    """
    Calculate appropriate bar width and positioning based on time interval and number of elements,
    using an algorithm similar to the frontend CombinedChart.vue
    Used by both draw_combined_chart and draw_gas_grouped_charts
    """
    # Convert time_interval_minutes to a number if it's a string
    try:
        time_interval_minutes = float(time_interval_minutes) if time_interval_minutes is not None else 60  # default to 60 min
    except (ValueError, TypeError):
        time_interval_minutes = 60

    if total_elements_in_group <= 0 or time_interval_minutes <= 0 or total_time_points <= 0:
        return 0.008, []  # Default width and empty offsets

    # Calculate base width for each time point interval (like frontend: totalBarWidth = chartWidth / numTimePoints)
    # Convert the time interval to matplotlib date units
    interval_width = (time_interval_minutes / 1440.0)  # Convert minutes to matplotlib date units
    
    # Add a gap between time groups (similar to frontend: barGap = totalBarWidth * 0.2)
    group_gap = interval_width * 0.2
    
    # Calculate the available width for bars within the group
    available_width_for_group = interval_width - group_gap
    
    # Calculate consistent bar width for all groups based on max elements that appear in any group
    # This is similar to the frontend approach: consistentBarWidth = availableWidth / maxBarsInAnyTimePoint
    if max_elements_in_any_group > 0:
        bar_width = available_width_for_group / max_elements_in_any_group
        # Limit the bar width to reasonable bounds (similar to frontend: Math.max(2, Math.min(15, ...)))
        max_reasonable_width = available_width_for_group * 0.8  # Don't use more than 80% of available space
        bar_width = min(bar_width, max_reasonable_width)
        bar_width = max(bar_width, 0.001)  # Minimum width
    else:
        bar_width = 0.005  # Default small width
    
    # Calculate gap between bars within the group
    if total_elements_in_group > 1:
        total_bars_width = bar_width * total_elements_in_group
        remaining_space = available_width_for_group - total_bars_width
        if remaining_space > 0:
            gap_within_group = remaining_space / max(total_elements_in_group, 1)
        else:
            gap_within_group = bar_width * 0.1  # Small gap if no space left
    else:
        gap_within_group = 0

    # Calculate offsets for each element in the group to center them within the group space
    offsets = []
    if total_elements_in_group > 1:
        # Similar to frontend: position bars in the center of their allocated time slot
        total_group_width = (bar_width * total_elements_in_group) + (gap_within_group * (total_elements_in_group - 1))
        start_offset = -total_group_width / 2 + bar_width / 2  # Center the group and position each bar
        
        for element_idx in range(total_elements_in_group):
            offset = start_offset + element_idx * (bar_width + gap_within_group)
            offsets.append(offset)
    else:
        # For single elements, center in the available space
        offsets = [0]
    
    return bar_width, offsets

def get_bar_chart_xticks_and_labels(timestamps, start_date, end_date):
    """
    Consistent x-axis ticks and labels for bar charts using the same logic as line charts
    Returns ticks, labels that can be used with ax.set_xticks and ax.set_xticklabels
    """
    # Determine appropriate tick intervals based on the time range
    time_delta = end_date - start_date
    total_hours = time_delta.total_seconds() / 3600  # Convert to hours
    
    # Determine which timestamps to label based on the same logic as date locators
    all_timestamp_indices = list(range(len(timestamps)))
    
    # Calculate which points to label using the same logic as set_x_axis_format
    max_labels = 6
    step = max(1, len(timestamps) // max_labels)
    time_points_to_label = []
    for i in range(0, len(timestamps), step):
        time_points_to_label.append(i)
        if len(time_points_to_label) >= max_labels:
            break
    
    # If we haven't reached the last timestamp, add it
    if len(timestamps) > 0 and time_points_to_label and time_points_to_label[-1] != len(timestamps) - 1:
        if len(time_points_to_label) < max_labels:
            time_points_to_label.append(len(timestamps) - 1)

    # Create labels only for selected time points, empty labels for others
    x_labels = []
    for i in range(len(timestamps)):
        if i in time_points_to_label:
            # Format based on the same logic used in set_x_axis_format
            if total_hours <= 12:  # Less than 12 hours: show every hour
                x_labels.append(timestamps[i].strftime('%H:%M'))
            elif total_hours <= 48:  # Less than 2 days: show every 2 hours
                x_labels.append(timestamps[i].strftime('%m/%d %H:%M'))
            elif total_hours <= 168:  # Less than 7 days: show every 6 hours
                x_labels.append(timestamps[i].strftime('%m/%d %H:%M'))
            elif total_hours <= 720:  # Less than 30 days: show daily
                x_labels.append(timestamps[i].strftime('%m/%d'))
            else:  # More than 30 days: show monthly
                x_labels.append(timestamps[i].strftime('%Y-%m'))
        else:
            x_labels.append('')  # Empty label for tick marks we don't want to show text for

    return all_timestamp_indices, x_labels

def parse_datetime_format(date_string):
    """
    Parse datetime string in format YYYYMMDDTHHMM
    Returns datetime object or raises ValueError for invalid format
    """
    if not date_string or len(date_string) != 13 or "T" not in date_string:
        raise ValueError("Invalid date format. Expected YYYYMMDDTHHMM")
    
    try:
        year = int(date_string[0:4])
        month = int(date_string[4:6])
        day = int(date_string[6:8])
        hour = int(date_string[9:11])
        minute = int(date_string[11:13])
        return datetime.datetime(year, month, day, hour, minute)
    except (ValueError, IndexError):
        raise ValueError("Invalid date format. Expected YYYYMMDDTHHMM")


#these are RGB colors
COLOUR_LIST = [
	mcolors.CSS4_COLORS["blue"],
	mcolors.CSS4_COLORS["orange"],
	mcolors.CSS4_COLORS["green"],
	mcolors.CSS4_COLORS["red"],
	mcolors.CSS4_COLORS["brown"],
	mcolors.CSS4_COLORS["pink"],
	mcolors.CSS4_COLORS["gray"],
	mcolors.CSS4_COLORS["olive"],
	mcolors.CSS4_COLORS["cyan"],
]


def getReport(getData):
    from .models import Job, Location
    import io
    from reportlab.pdfgen import canvas as pdfcanvas
    
    # Import the parse function locally if needed
    # parse_datetime_format is already defined in this module
    
    # Get parameters from the request data
    job_id = getData.get('selected_job')
    report_options = getData.get('report_options', {})
    start_date_str = getData.get('start_date')
    end_date_str = getData.get('end_date')
    interval = getData.get('interval', 60)
    
    # Capture the time when the report is being generated
    import datetime
    generation_datetime = datetime.datetime.now()
    
    # Fetch the job
    job = Job.objects.get(id=job_id) if job_id else None
    headerString = f"Job: {job.label if job else 'All Jobs'}"
    
    # Extract date parameters
    start_date = None
    stop_date = None
    if start_date_str:
        start_date = parse_datetime_format(start_date_str)
    if end_date_str:
        stop_date = parse_datetime_format(end_date_str)
    
    # Get job address - use the job's suburb or get from a location
    address = job.suburb if job and job.suburb else ""
    if not address and job:
        # Try to get address from the first location associated with the job
        first_location = job.location_set.first()
        if first_location and first_location.address:
            address = first_location.address
    
    # Create an in-memory buffer for the PDF
    report_buffer = io.BytesIO()
    
    # Create the PDF canvas with A4 page size
    canvas = pdfcanvas.Canvas(report_buffer, pagesize=A4)
    
    # Add the title page
    draw_title_page(canvas, job.label if job else 'All Jobs', address, start_date, stop_date, interval, generation_datetime)
    
    # Only proceed if map option is selected
    if report_options.get('map', False) and job:
        # Get all locations for the job that have coordinates for mapping
        data = []
        location_objects = Job.objects.get(id=job_id).location_set.all()
        for location in location_objects:
            if location.latitude and location.longitude:  # Only include locations with coordinates
                data.append({
                    "location": location.label,
                    "latitude": location.latitude,
                    "longitude": location.longitude
                })
        
        if len(data) > 0:
            if os.path.exists(settings.STATICFILES_DIRS[0]):
                draw_map(canvas, data, headerString, generation_datetime)
        else:
            canvas.drawString(10*cm, 15*cm, "No Map Data")
    
    if report_options.get('summary', False):
        # Draw summary table if requested
        if report_options.get('summaryTable', True):  # Default to true if not specified
            start_date_str = getData.get('start_date')
            end_date_str = getData.get('end_date')
            if start_date_str and end_date_str:
                start_date = parse_datetime_format(start_date_str)
                end_date = parse_datetime_format(end_date_str)
                # Call drawSummaryTable with the needed parameters
                drawSummaryTable(canvas, start_date, end_date, interval, 
                                getData.get('selected_locations', []), getData.get('selected_gases', []))
                # Add page break after table if charts will also be drawn
                if report_options.get('summaryCharts', True):
                    close_page(canvas, headerString, generation_datetime)
        
        # Draw summary charts if requested
        if report_options.get('summaryCharts', True):  # Default to true if not specified
            start_date_str = getData.get('start_date')
            end_date_str = getData.get('end_date')
            if start_date_str and end_date_str:
                start_date = parse_datetime_format(start_date_str)
                end_date = parse_datetime_format(end_date_str)
                # Get chart type from report options
                chart_type = 'bar'  # Default to bar for summary charts
                # Get threshold option for summary charts
                show_threshold = report_options.get('summaryChartWithThreshold', True)
                # Call draw_summary_charts with the needed parameters
                draw_summary_charts(canvas, start_date, end_date, interval,
                                   getData.get("selected_locations", []), 
                                   getData.get("selected_gases", []), headerString, 
                                   generation_datetime, show_threshold=show_threshold)
    
    
    if report_options.get("combinedChart", False):
        # Draw combined chart if requested
        start_date_str = getData.get("start_date")
        end_date_str = getData.get("end_date")
        if start_date_str and end_date_str:
            start_date = parse_datetime_format(start_date_str)
            end_date = parse_datetime_format(end_date_str)
            # Get chart type from report options, specifically for combined charts
            chart_type = getData.get('report_options', {}).get('combinedChartType', 'line')
            # Get grouping option - default to 'location' to maintain backward compatibility
            group_by = getData.get('report_options', {}).get('combinedChartGroupBy', 'location')
            # Get stat type - default to 'avg' to maintain backward compatibility
            stat_type = getData.get('report_options', {}).get('combinedChartStatType', 'avg')
            # Call draw_combined_chart with the needed parameters
            draw_combined_chart(canvas, start_date, end_date, interval,
                               getData.get("selected_locations", []), 
                               getData.get("selected_gases", []), headerString, generation_datetime, chart_type, stat_type, group_by)
    
    if report_options.get("individualChart", False):
        # Draw charts grouped by gas if requested
        start_date_str = getData.get("start_date")
        end_date_str = getData.get("end_date")
        if start_date_str and end_date_str:
            start_date = parse_datetime_format(start_date_str)
            end_date = parse_datetime_format(end_date_str)
            # Get chart type from report options, specifically for individual charts
            chart_type = getData.get('report_options', {}).get('individualChartType', 'line')
            # Call draw_gas_grouped_charts with the needed parameters
            draw_gas_grouped_charts(canvas, start_date, end_date, interval,
                                   getData.get("selected_locations", []), 
                                   getData.get("selected_gases", []), 
                                   report_options, headerString, generation_datetime, chart_type)

    close_page(canvas, headerString, generation_datetime)
    
    canvas.save()
    report_buffer.seek(0)
    return report_buffer


def drawSummaryTable(canvas, start_date, end_date, interval, selected_locations, selected_gases):
    # Add the header
    canvas.setFont("Courier-Bold", 14)  # Use bold font for header
    interval_str = f"{interval} Minute Intervals" if interval else "Intervals"
    start_date_str = start_date.strftime('%Y-%m-%d %H:%M') if start_date else 'Unknown'
    end_date_str = end_date.strftime('%Y-%m-%d %H:%M') if end_date else 'Unknown'
    header_text1 = f"Summary table - {interval_str}"
    header_text2 = "for"
    header_text3 = f"{start_date_str} - {end_date_str}"
    
    # Center align each header line
    text_width1 = canvas.stringWidth(header_text1, "Courier-Bold", 14)
    text_width2 = canvas.stringWidth(header_text2, "Courier-Bold", 14)
    text_width3 = canvas.stringWidth(header_text3, "Courier-Bold", 14)
    
    # Calculate center positions (A4 width is about 21cm, centered around 10.5cm)
    x_pos1 = 10.5*cm - text_width1/2
    x_pos2 = 10.5*cm - text_width2/2
    x_pos3 = 10.5*cm - text_width3/2
    
    canvas.drawString(x_pos1, 26*cm, header_text1)  # 5mm spacing
    canvas.drawString(x_pos2, 25.5*cm, header_text2)  # 5mm spacing
    canvas.drawString(x_pos3, 25*cm, header_text3)  # 5mm spacing  # Indented by 1.5cm to visually separate
    canvas.setFont("Courier", 14)  # Reset to normal font
    
    # This function fetches summary data similar to retrieve_summary_for_gas in views.py

    # Build the queryset with filters
    queryset = SensorReading.objects.filter(
        validation__isnull=True  # Only include valid readings
    ).select_related('sensor', 'location', 'location__job')
    
    # Apply date range filter
    queryset = queryset.filter(
        log_time__gte=start_date,
        log_time__lte=end_date
    )
    
    # Apply location filter if specified
    if selected_locations:
        queryset = queryset.filter(location_id__in=selected_locations)
    
    # Apply gas filter if specified
    if selected_gases:
        queryset = queryset.filter(sensor__gas_code__in=selected_gases)
    
    # Group readings by time intervals according to the specified interval
    # First, we'll get all the relevant data, then group it by intervals
    readings = queryset.order_by('log_time')
    
    # Convert interval to integer to ensure it's a number
    try:
        interval_int = int(float(interval)) if interval is not None else 60
    except (ValueError, TypeError):
        interval_int = 60  # Default to 60 minutes if conversion fails
    
    
    if interval_int > 0:  # Only group by intervals if interval is positive
        from datetime import timedelta
        
        # CALCULATION 1: Time period average for each location/gas combination using AVG aggregate
        # Calculate the overall average across the entire time period for each location/gas using Django's AVG function
        time_period_avgs = queryset.values('location__label', 'sensor__gas_code').annotate(
            avg_reading=Avg('reading'),
            count_readings=Count('id')
        ).order_by('location__label', 'sensor__gas_code')
        
        # Convert to a more convenient format
        time_period_stats = {}
        for result in time_period_avgs:
            key = (result['location__label'], result['sensor__gas_code'])
            time_period_stats[key] = {
                'avg': result['avg_reading'],
                'count': result['count_readings']
            }
        
        # CALCULATION 2: Interval averages for each location/gas combination
        # Group readings by time intervals and calculate average for each interval
        interval_averages_by_location_gas = defaultdict(list)
        
        # Process readings by time intervals
        current_time = start_date
        while current_time < end_date:
            interval_end = current_time + timedelta(minutes=interval_int)
            if interval_end > end_date:
                interval_end = end_date
            
            # Get readings for this interval (current_time, interval_end] format
            interval_readings = []
            for reading in readings:
                if current_time < reading.log_time <= interval_end:
                    interval_readings.append(reading)
            
            # Calculate average for each location/gas in this interval
            interval_location_gas_stats = defaultdict(lambda: {'sum': 0, 'count': 0})
            for reading in interval_readings:
                key = (reading.location.label, reading.sensor.gas_code)
                interval_location_gas_stats[key]['sum'] += reading.reading
                interval_location_gas_stats[key]['count'] += 1
            
            # Calculate and store interval averages
            for (location_label, gas_code), stats in interval_location_gas_stats.items():
                if stats['count'] > 0:
                    interval_avg = stats['sum'] / stats['count']
                    interval_averages_by_location_gas[(location_label, gas_code)].append(interval_avg)
            
            current_time = interval_end
        
        # CALCULATION 3: Individual reading max/min for each location/gas combination
        individual_stats = defaultdict(lambda: {'max': float('-inf'), 'min': float('inf')})
        for reading in readings:
            key = (reading.location.label, reading.sensor.gas_code)
            individual_stats[key]['max'] = max(individual_stats[key]['max'], reading.reading)
            individual_stats[key]['min'] = min(individual_stats[key]['min'], reading.reading)
        
    # Prepare table data with aggregated interval-based statistics
    table_data = [['Loc', 'Gas', 'Avg', 'N', 'Max Int', 'Min Int', 'Max Ind', 'Min Ind']]
    
    for (location_label, gas_code) in time_period_stats.keys():
        # CALCULATION 1: Time period average using AVG aggregate
        total_stats = time_period_stats[(location_label, gas_code)]
        time_period_avg = total_stats['avg']
        
        # CALCULATION 2: Max/Min of interval averages
        interval_avgs = interval_averages_by_location_gas[(location_label, gas_code)]
        max_interval_avg = max(interval_avgs) if interval_avgs else None
        min_interval_avg = min(interval_avgs) if interval_avgs else None
        
        # Debug: print max_interval_avg with location and gas
        if max_interval_avg is not None:
            print(f"DEBUG_MAX_INT: Location={location_label}, Gas={gas_code}, Max Interval Average={max_interval_avg:.2f}")
        
        # CALCULATION 3: Individual reading max/min
        ind_stats = individual_stats[(location_label, gas_code)]
        max_individual = ind_stats['max'] if ind_stats['max'] != float('-inf') else None
        min_individual = ind_stats['min'] if ind_stats['min'] != float('inf') else None
        
        row = [
            location_label,
            get_gas_display_name(gas_code),  # Use the display name instead of the code
            f"{time_period_avg:.2f}" if time_period_avg is not None else 'N/A',  # Avg (time period average using AVG aggregate)
            total_stats['count'],  # N (total count)
            f"{max_interval_avg:.2f}" if max_interval_avg is not None else 'N/A',  # Max Int (max of interval averages)
            f"{min_interval_avg:.2f}" if min_interval_avg is not None else 'N/A',  # Min Int (min of interval averages)
            f"{max_individual:.2f}" if max_individual is not None else 'N/A',  # Max Ind (max individual)
            f"{min_individual:.2f}" if min_individual is not None else 'N/A'   # Min Ind (min individual)
        ]
        table_data.append(row)
    
    # Draw a nice table
    if len(table_data) > 1:  # If there's data to show (header + at least 1 row)
        y_pos = 23.5*cm  # Adjusted to start below the lowest header line at 25*cm with some spacing
        row_height = 0.6*cm
        col_widths = [2.4*cm, 2.4*cm, 2.4*cm, 1.6*cm, 2.4*cm, 2.4*cm, 2.4*cm, 2.4*cm]  # Increased widths by ~3.2cm total
        
        # Define alignment for each column (0=left, 1=center, 2=right)
        col_alignments = [0, 0, 0, 0, 0, 0, 0, 0]  # Left align all columns
        
        # Draw table header with different color
        canvas.setFillColorRGB(0.8, 0.8, 0.8)  # Light gray
        canvas.rect(1*cm, y_pos - row_height, sum(col_widths), row_height, fill=1)
        canvas.setFillColorRGB(0, 0, 0)  # Black text
        
        # Adjust vertical offset to fix the issue where text was about 2mm too high
        # The original offset of 0.4*cm needs to be reduced by ~2mm (0.2cm) to move text down
        vertical_offset = 0.2*cm  # Reduced from 0.4*cm to move text down by ~2mm
        
        # Draw header cells with proper alignment
        x_pos = 1*cm
        for j, header in enumerate(table_data[0]):
            # Calculate position based on alignment
            cell_width = col_widths[j]
            text_width = canvas.stringWidth(str(header), "Courier", 10)
            
            if col_alignments[j] == 0:  # Left align
                text_x = x_pos + 2
            elif col_alignments[j] == 1:  # Center align
                text_x = x_pos + (cell_width - text_width) / 2
            else:  # Right align (2)
                text_x = x_pos + cell_width - text_width - 2
            
            canvas.drawString(text_x, y_pos - row_height + vertical_offset, str(header))
            x_pos += col_widths[j]
        
        # Draw data rows with alternating colors
        for i, row in enumerate(table_data[1:], 1):
            # Alternate row colors
            if i % 2 == 0:
                canvas.setFillColorRGB(0.95, 0.95, 0.95)  # Lighter gray for even rows
            else:
                canvas.setFillColorRGB(1, 1, 1)  # White for odd rows
            canvas.rect(1*cm, y_pos - i*row_height - row_height, sum(col_widths), row_height, fill=1)
            canvas.setFillColorRGB(0, 0, 0)  # Black text
            
            # Draw data cells with proper alignment
            x_pos = 1*cm
            for j, cell in enumerate(row):
                cell_width = col_widths[j]
                text_content = str(cell)
                text_width = canvas.stringWidth(text_content, "Courier", 10)
                
                if col_alignments[j] == 0:  # Left align
                    text_x = x_pos + 2
                elif col_alignments[j] == 1:  # Center align
                    text_x = x_pos + (cell_width - text_width) / 2
                else:  # Right align (2)
                    text_x = x_pos + cell_width - text_width - 2
                
                canvas.drawString(text_x, y_pos - i*row_height - row_height + vertical_offset, text_content)
                x_pos += col_widths[j]
        
        # Draw table borders
        canvas.setFillColorRGB(0, 0, 0)
        canvas.rect(1*cm, y_pos - len(table_data)*row_height, sum(col_widths), len(table_data)*row_height)
        
        # Draw vertical lines
        x_pos = 1*cm
        for width in col_widths:
            canvas.line(x_pos, y_pos, x_pos, y_pos - len(table_data)*row_height)
            x_pos += width
        canvas.line(x_pos, y_pos, x_pos, y_pos - len(table_data)*row_height)
        
        # Draw horizontal lines
        for i in range(len(table_data)):
            canvas.line(1*cm, y_pos - i*row_height, 1*cm + sum(col_widths), y_pos - i*row_height)
        
        # Bottom line
        canvas.line(1*cm, y_pos - len(table_data)*row_height, 1*cm + sum(col_widths), y_pos - len(table_data)*row_height)
        
        # Add footnote at the bottom of the page
        canvas.setFont("Courier", 8)  # Smaller font for footnote
        canvas.drawString(1*cm, 2*cm, "CO, H2S in ppm, VOC in ppm/isobutylene, LEL in %LEL, O2 in %v/v")
    else:
        # If no data, just show a message
        canvas.drawString(5*cm, 25*cm, "No summary data available for the selected criteria")

def draw_map(canvas, data, header_string, generation_datetime=None):
    """
    Draws the map for the PDF report
    """
    # Add the header
    canvas.setFont("Courier-Bold", 14)  # Use bold font for header
    # Calculate center position for the header
    header_text = "Map - Locations"
    text_width = canvas.stringWidth(header_text, "Courier-Bold", 14)
    center_x = 10.5*cm - text_width/2  # Center of A4 page (21cm/2 = 10.5cm)
    canvas.drawString(center_x, 27*cm, header_text)
    canvas.setFont("Courier", 14)  # Reset to normal font
    
    extent = calculate_map_extent(data)
    if len(extent):
        zoom_level = estimate_zoom_level(extent, (15/2.54, 15/2.54))
        imagery = OSM()
        fig = plt.figure(figsize=(15/2.54, 15/2.54))
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    

        ax.set_extent([extent[0], extent[1], extent[2], extent[3]], crs=ccrs.PlateCarree())
        # Imagery plus zoom level
        ax.add_image(imagery, zoom_level)
        
        # Keeps track of location labels so they are only drawn once
        existing_locations = []
        for d in data:
            if d["location"] not in existing_locations and d["latitude"] and d["longitude"]:
                # Add the location label centered on the correct location
                ax.text(d["longitude"], d["latitude"], f"{d['location']}", transform=ccrs.PlateCarree(), 
                        horizontalalignment='center', verticalalignment='center', fontsize=10, zorder=10, 
                        bbox=dict(boxstyle="round,pad=0.2", facecolor="yellow", alpha=0.7))
                existing_locations.append(d["location"])
        plt.savefig(os.path.join(settings.STATICFILES_DIRS[0], "map.png"), format="png", bbox_inches="tight", dpi=150)
        plt.close()
        # Position the map below the header (moved from 1*cm to lower position to account for header)
        canvas.drawImage(os.path.join(settings.STATICFILES_DIRS[0], "map.png"), 1*cm, 10*cm, width=19*cm, height=16*cm)
    else:
        canvas.rect(5*cm, 15*cm, 10*cm, 10*cm, fill=0)
        canvas.drawString(10*cm, 20*cm, "No Map Data")
    close_page(canvas, header_string, generation_datetime)


def calculate_map_extent(data):
    """
    Calculates the map extent based on the data provided
    """
    lats = []
    lons = []
    # Amount of extra space around extent
    padding_factor = 0.05
    min_span = 0.005
    for d in data:
        if d["latitude"] and d["longitude"]:
            lats.append(d["latitude"])
            lons.append(d["longitude"])
    if len(lats) > 0 and len(lons) > 0:
        lat_min, lat_max = min(lats), max(lats)
        lon_min, lon_max = min(lons), max(lons)
        lat_span = lat_max - lat_min
        if lat_span < min_span:
            lat_span = min_span

        lon_span = lon_max - lon_min
        if lon_span < min_span:
            lon_span = min_span
        lat_padding = lat_span * padding_factor
        lon_padding = lon_span * padding_factor

        extent = [
            lon_min - lon_padding,
            lon_max + lon_padding,
            lat_min - lat_padding,
            lat_max + lat_padding
        ]
        return extent
    return []


# Too smart for me. This is from qwen
def estimate_zoom_level(extent, figsize=(10, 10), dpi=150):
    """
    Estimates the Web Mercator zoom level based on a map extent and target figure size.

    Args:
        extent (tuple): A tuple of (lon_min, lon_max, lat_min, lat_max).
        figsize (tuple, optional): Figure size (width, height) in inches. Defaults to (10, 10).
        dpi (int, optional): Dots per inch of the figure. Defaults to 100.

    Returns:
        int: The estimated integer zoom level.
    """
    lon_min, lon_max, lat_min, lat_max = extent

    # --- 1. Calculate Angular Spans ---
    delta_lon = abs(lon_max - lon_min)
    delta_lat = abs(lat_max - lat_min)

    # --- 2. Approximate Meters per Degree (at central latitude) ---
    center_lat = (lat_min + lat_max) / 2.0
    meters_per_degree_lat = 111319.9 # Approximate meters per degree latitude
    meters_per_degree_lon = meters_per_degree_lat * np.cos(np.radians(center_lat))

    # --- 3. Estimate Map Physical Size (meters) ---
    map_width_meters = delta_lon * meters_per_degree_lon
    map_height_meters = delta_lat * meters_per_degree_lat
    # Use diagonal for a more robust size estimate
    map_diag_meters = np.sqrt(map_width_meters**2 + map_height_meters**2)

    # --- 4. Calculate Figure Size (pixels) ---
    fig_width_px = figsize[0] * dpi
    fig_height_px = figsize[1] * dpi
    fig_diag_px = np.sqrt(fig_width_px**2 + fig_height_px**2)

    # --- 5. Estimate Meters per Pixel ---
    if fig_diag_px <= 0:
        return 13 # Avoid division by zero, return a default zoom
    meters_per_pixel = map_diag_meters / fig_diag_px

    # --- 6. Relate Meters per Pixel to Web Mercator Zoom ---
    # Resolution at zoom 0 at the equator (meters per pixel)
    resolution_at_equator = 156543.0
    cos_lat = np.cos(np.radians(center_lat))

    # Avoid potential math errors if meters_per_pixel is unexpectedly large or zero
    if meters_per_pixel <= 0 or np.isnan(meters_per_pixel) or np.isinf(meters_per_pixel):
        return 19 # Default to max zoom if calculation fails

    # Calculate zoom level using the Web Mercator formula rearranged
    # resolution = (156543 * cos(lat)) / (2^zoom)
    # => zoom = log2((156543 * cos(lat)) / resolution)
    try:
        zoom_float = np.log2((resolution_at_equator * cos_lat) / meters_per_pixel)
        # Round to the nearest integer
        zoom_level = int(round(zoom_float))
    except (ValueError, OverflowError):
        # Fallback if log calculation fails
        zoom_level = 13

    # --- 7. Clamp to Typical OSM Zoom Levels ---
    zoom_level = max(0, min(zoom_level, 19))
    print(f'zoom level = {zoom_level}')
    return zoom_level

def draw_combined_chart(canvas, start_date, end_date, interval, selected_locations, selected_gases, header_string, generation_datetime=None, chart_type='line', stat_type='avg', group_by='location'):
    """
    Draws a combined chart showing various statistics for each interval for selected locations and gases.
    Supports different chart types (line/bar), statistics (avg/min/max/count), and grouping (by location/gas).
    """
    from .models import SensorReading, Location, Sensor
    
    # Add the header
    canvas.setFont("Courier-Bold", 14)  # Use bold font for header
    # Calculate center position for the header
    header_text = f"Combined Chart - {stat_type.title()} Readings"
    text_width = canvas.stringWidth(header_text, "Courier-Bold", 14)
    center_x = 10.5*cm - text_width/2  # Center of A4 page (21cm/2 = 10.5cm)
    canvas.drawString(center_x, 27*cm, header_text)
    canvas.setFont("Courier", 14)  # Reset to normal font
    
    # Build the queryset with filters
    queryset = SensorReading.objects.filter(
        validation__isnull=True  # Only include valid readings
    ).select_related('sensor', 'location', 'location__job')
    
    # Apply date range filter
    queryset = queryset.filter(
        log_time__gte=start_date,
        log_time__lte=end_date
    )
    
    # Apply location filter if specified
    if selected_locations:
        queryset = queryset.filter(location_id__in=selected_locations)
    
    # Apply gas filter if specified
    if selected_gases:
        queryset = queryset.filter(sensor__gas_code__in=selected_gases)
    
    # Get all the relevant data
    readings = queryset.order_by('log_time')

    # Convert interval to integer to ensure it's a number
    try:
        interval_int = int(float(interval)) if interval is not None else 60
    except (ValueError, TypeError):
        interval_int = 60  # Default to 60 minutes if conversion fails

    if not readings.exists():
        canvas.drawString(5*cm, 25*cm, "No data available for the selected criteria")
        close_page(canvas, header_string)
        return

    # Group readings by time intervals and calculate statistics for each combination
    interval_stats_by_location_gas = defaultdict(lambda: {'timestamps': [], 'values': []})

    from datetime import timedelta
    current_time = start_date
    all_timestamps = []  # Keep track of unique timestamps in chronological order
    
    while current_time < end_date:
        interval_end = current_time + timedelta(minutes=interval_int)
        if interval_end > end_date:
            interval_end = end_date

        # Get readings for this interval (current_time, interval_end] format
        interval_readings = []
        for reading in readings:
            if current_time < reading.log_time <= interval_end:
                interval_readings.append(reading)

        # Calculate statistic for each location/gas in this interval
        interval_location_gas_stats = defaultdict(lambda: {'readings': []})
        for reading in interval_readings:
            key = (reading.location.label, reading.sensor.gas_code)
            interval_location_gas_stats[key]['readings'].append(reading.reading)

        # Calculate and store interval statistics
        for (location_label, gas_code), stats in interval_location_gas_stats.items():
            if len(stats['readings']) > 0:
                if stat_type == 'avg':
                    value = sum(stats['readings']) / len(stats['readings'])
                elif stat_type == 'min':
                    value = min(stats['readings'])
                elif stat_type == 'max':
                    value = max(stats['readings'])
                elif stat_type == 'count':
                    value = len(stats['readings'])
                else:
                    value = sum(stats['readings']) / len(stats['readings'])  # Default to avg
                
                # For display purposes, align the timestamp with the start of the interval (on the hour)
                # If the interval starts on an hour boundary, use that as the display timestamp
                display_timestamp = current_time
                
                interval_stats_by_location_gas[(location_label, gas_code)]['timestamps'].append(display_timestamp)
                interval_stats_by_location_gas[(location_label, gas_code)]['values'].append(value)
                
                # Only add to all_timestamps if not already present
                if not any(abs((ts - display_timestamp).total_seconds()) < 60 for ts in all_timestamps):
                    all_timestamps.append(display_timestamp)

        current_time = interval_end

    if not interval_stats_by_location_gas or not all_timestamps:
        canvas.drawString(5*cm, 25*cm, "No data available for the selected criteria")
        close_page(canvas, header_string)
        return

    # Get unique gases and locations that have data
    gases = sorted(list(set(gas for (loc, gas) in interval_stats_by_location_gas.keys())))
    locations = sorted(list(set(loc for (loc, gas) in interval_stats_by_location_gas.keys())))
    timestamps = sorted(all_timestamps)

    # Create matplotlib figure for combined chart
    fig, ax = plt.subplots(figsize=(15/2.54, 15/2.54))  # Convert cm to inches for matplotlib

    if chart_type == 'bar':
        # Create grouped bar chart using categorical x-axis approach
        n_locations = len(locations)
        n_gases = len(gases)
        n_timestamps = len(timestamps)
        
        if n_timestamps == 0:
            canvas.drawString(5*cm, 25*cm, "No data available for the selected criteria")
            close_page(canvas, header_string)
            return

        import matplotlib.dates as mdates
        from datetime import timedelta
        import numpy as np
        
        import matplotlib.dates as mdates
        from datetime import timedelta
        import numpy as np
        import math
        
        # Calculate max elements in any group and total time points for shared function
        max_elements_in_any_group = len(gases) if group_by == 'location' else len(locations)
        total_time_points = len(timestamps) if timestamps else 1
        
        # Create a mapping to track which labels have already been used for legend
        legend_added = set()
        
        # Plot bars based on grouping with datetime positioning for consistent x-axis
        if group_by == 'location':
            # For location grouping: iterate through timestamps, then each location's gases
            for t_idx, timestamp in enumerate(timestamps):
                base_time_num = mdates.date2num(timestamp)
                
                # For this timestamp, group bars by location first
                for loc_idx, location_label in enumerate(locations):
                    # Use the shared function for consistent bar width calculation based on time interval
                    total_elements_in_group = len(gases)  # Total gases for this location
                    bar_width, offsets = calculate_grouped_bar_positions_and_widths(
                        interval_int, total_elements_in_group, max_elements_in_any_group, total_time_points
                    )
                    
                    # Calculate positions for all gas bars using the shared function
                    for gas_idx, gas_code in enumerate(gases):
                        # Find the data value for this location-gas-timestamp combination
                        y_value = 0
                        for data_idx, data_timestamp in enumerate(interval_stats_by_location_gas.get((location_label, gas_code), {}).get('timestamps', [])):
                            time_diff = abs((data_timestamp - timestamp).total_seconds())
                            if time_diff <= (interval_int * 60) / 2:  # Within half the interval
                                y_value = interval_stats_by_location_gas[(location_label, gas_code)]['values'][data_idx]
                                break

                        # Get the offset for this specific gas using the shared function
                        position_offset = offsets[gas_idx] if gas_idx < len(offsets) else 0
                        bar_pos = base_time_num + position_offset
                        
                        # Use a unique color for this location-gas combination
                        color_index = loc_idx * n_gases + gas_idx
                        color = COLOUR_LIST[color_index % len(COLOUR_LIST)]
                        
                        # Create a unique identifier for this combination to avoid duplicate legend entries
                        combination_key = f"{location_label}-{gas_code}"
                        
                        # Only add label for legend on the first occurrence
                        if combination_key not in legend_added:
                            label = f"{location_label} - {get_gas_display_name(gas_code)}"
                            legend_added.add(combination_key)
                        else:
                            label = ""
                        
                        if y_value is not None and not (isinstance(y_value, float) and np.isnan(y_value)):
                            ax.bar([bar_pos], [y_value], width=bar_width, color=color, alpha=0.7, label=label)

        else:  # group_by == 'gas'
            # For gas grouping: iterate through timestamps, then each gas's locations
            for t_idx, timestamp in enumerate(timestamps):
                base_time_num = mdates.date2num(timestamp)
                
                # For this timestamp, group bars by gas first
                for gas_idx, gas_code in enumerate(gases):
                    # Use the shared function for consistent bar width calculation based on time interval
                    total_elements_in_group = len(locations)  # Total locations for this gas
                    bar_width, offsets = calculate_grouped_bar_positions_and_widths(
                        interval_int, total_elements_in_group, max_elements_in_any_group, total_time_points
                    )
                    
                    for loc_idx, location_label in enumerate(locations):
                        # Find the data value for this gas-location-timestamp combination
                        y_value = 0
                        for data_idx, data_timestamp in enumerate(interval_stats_by_location_gas.get((location_label, gas_code), {}).get('timestamps', [])):
                            time_diff = abs((data_timestamp - timestamp).total_seconds())
                            if time_diff <= (interval_int * 60) / 2:  # Within half the interval
                                y_value = interval_stats_by_location_gas[(location_label, gas_code)]['values'][data_idx]
                                break

                        # Get the offset for this specific location using the shared function
                        position_offset = offsets[loc_idx] if loc_idx < len(offsets) else 0
                        bar_pos = base_time_num + position_offset
                        
                        # Use a unique color for this gas-location combination
                        color_index = gas_idx * n_locations + loc_idx
                        color = COLOUR_LIST[color_index % len(COLOUR_LIST)]
                        
                        # Create a unique identifier for this combination to avoid duplicate legend entries
                        combination_key = f"{gas_code}-{location_label}"
                        
                        # Only add label for legend on the first occurrence
                        if combination_key not in legend_added:
                            label = f"{get_gas_display_name(gas_code)} - {location_label}"
                            legend_added.add(combination_key)
                        else:
                            label = ""
                        
                        if y_value is not None and not (isinstance(y_value, float) and np.isnan(y_value)):
                            ax.bar([bar_pos], [y_value], width=bar_width, color=color, alpha=0.7, label=label)

        # Format x-axis dates to show the entire time period with sensible ticks using the same logic as line charts
        ax.set_xlim(start_date, end_date)  # Use datetime x-axis limits
        set_x_axis_format(ax, start_date, end_date)
        
        ax.set_xlabel('Time')
        ax.set_ylabel(f'{stat_type.title()} Reading')

    else:  # Default to line chart (time series)
        # Plot each location/gas combination for line chart
        color_idx = 0
        for (location_label, gas_code), data in interval_stats_by_location_gas.items():
            if len(data['timestamps']) > 0 and len(data['values']) > 0:
                color = COLOUR_LIST[color_idx % len(COLOUR_LIST)]
                label = f"{location_label} - {get_gas_display_name(gas_code)}"
                ax.plot(data['timestamps'], data['values'], label=label, color=color, marker='o', markersize=4)
                color_idx += 1
        
        ax.set_xlabel('Time')
        ax.set_ylabel(f'{stat_type.title()} Reading')
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        ax.grid(True, linestyle='--', alpha=0.6)
        
        # Format x-axis dates to show the entire time period with sensible ticks
        ax.set_xlim(start_date, end_date)  # Set x-axis limits to the full time period
        set_x_axis_format(ax, start_date, end_date)

    # Add legend to show all data series (both for line and bar charts)
    handles, labels = ax.get_legend_handles_labels()
    # Remove duplicates while keeping order
    unique_labels = []
    unique_handles = []
    for handle, label in zip(handles, labels):
        if label and label not in unique_labels:
            unique_labels.append(label)
            unique_handles.append(handle)
    if unique_labels:  # Only add legend if there are labels
        ax.legend(unique_handles, unique_labels, bbox_to_anchor=(1.05, 1), loc='upper left')
    
    # Add grid for better readability
    ax.grid(True, linestyle='--', alpha=0.6)

    # Save the plot to a temporary file
    chart_path = os.path.join(settings.STATICFILES_DIRS[0], "combined_chart.png") if hasattr(settings, 'STATICFILES_DIRS') and settings.STATICFILES_DIRS else "/tmp/combined_chart.png"
    plt.savefig(chart_path, format="png", bbox_inches="tight", dpi=150)
    plt.close()
    
    # Draw the chart on the PDF
    if os.path.exists(chart_path):
        # Position the chart below the header
        canvas.drawImage(chart_path, 1*cm, 8*cm, width=19*cm, height=16*cm)
    else:
        canvas.drawString(5*cm, 20*cm, "Error generating chart")
    
    close_page(canvas, header_string, generation_datetime)


def draw_gas_grouped_charts(canvas, start_date, end_date, interval, selected_locations, selected_gases, report_options, header_string, generation_datetime=None, chart_type='line'):
    """
    Draws charts grouped by gas instead of individual location-gas combinations, with thresholds as horizontal lines
    """
    from .models import SensorReading, Location, Sensor
    
    # Get chart type from report options, specifically for individual charts
    # If individualChartType is available, use it; otherwise fall back to general chart_type
    chart_type = report_options.get('individualChartType', chart_type)
    
    # Build the queryset with filters
    queryset = SensorReading.objects.filter(
        validation__isnull=True  # Only include valid readings
    ).select_related('sensor', 'location', 'location__job')
    
    # Apply date range filter
    queryset = queryset.filter(
        log_time__gte=start_date,
        log_time__lte=end_date
    )
    
    # Apply location filter if specified
    if selected_locations:
        queryset = queryset.filter(location_id__in=selected_locations)
    
    # Apply gas filter if specified
    if selected_gases:
        queryset = queryset.filter(sensor__gas_code__in=selected_gases)
    
    # Get all the relevant data
    readings = queryset.order_by('log_time')

    # Convert interval to integer to ensure it's a number
    try:
        interval_int = int(float(interval)) if interval is not None else 60
    except (ValueError, TypeError):
        interval_int = 60  # Default to 60 minutes if conversion fails

    if not readings.exists():
        canvas.drawString(5*cm, 25*cm, "No data available for the selected criteria")
        close_page(canvas, header_string)
        return

    # Group readings by time intervals and calculate average for each combination
    interval_averages_by_location_gas = defaultdict(lambda: {'timestamps': [], 'averages': []})

    from datetime import timedelta
    current_time = start_date
    while current_time < end_date:
        interval_end = current_time + timedelta(minutes=interval_int)
        if interval_end > end_date:
            interval_end = end_date

        # Get readings for this interval (current_time, interval_end] format
        interval_readings = []
        for reading in readings:
            if current_time < reading.log_time <= interval_end:
                interval_readings.append(reading)

        # Calculate average for each location/gas in this interval
        interval_location_gas_stats = defaultdict(lambda: {'sum': 0, 'count': 0})
        for reading in interval_readings:
            key = (reading.location.label, reading.sensor.gas_code)
            interval_location_gas_stats[key]['sum'] += reading.reading
            interval_location_gas_stats[key]['count'] += 1

        # Calculate and store interval averages
        for (location_label, gas_code), stats in interval_location_gas_stats.items():
            if stats['count'] > 0:
                interval_avg = stats['sum'] / stats['count']
                interval_averages_by_location_gas[(location_label, gas_code)]['timestamps'].append(
                    current_time
                )  # Use start of interval for plotting (at time of reading)
                interval_averages_by_location_gas[(location_label, gas_code)]['averages'].append(interval_avg)

        current_time = interval_end

    # Group the data by gas
    data_by_gas = defaultdict(list)
    for (location_label, gas_code), data in interval_averages_by_location_gas.items():
        if len(data['timestamps']) > 0 and len(data['averages']) > 0:
            data_by_gas[gas_code].append({
                'location_label': location_label,
                'timestamps': data['timestamps'],
                'averages': data['averages']
            })

    # Get default thresholds (same as in the frontend)
    thresholds = {
        'CO': 50.0,  # Carbon Monoxide
        'HS': 10.0,  # Hydrogen Sulfide
        'LE': 5.0,   # LEL (Lower Explosive Limit)
        'O2': 19.5,  # Oxygen
        'VO': 50.0   # VOC (Volatile Organic Compounds)
    }
    
    # Draw a chart for each gas showing all locations for that gas
    for gas_code, locations_data in data_by_gas.items():
        # Add the header for this chart
        canvas.setFont("Courier-Bold", 14)  # Use bold font for header
        # Calculate center position for the header
        header_text = f"Chart - {get_gas_display_name(gas_code)} Readings by Location"
        text_width = canvas.stringWidth(header_text, "Courier-Bold", 14)
        center_x = 10.5*cm - text_width/2  # Center of A4 page (21cm/2 = 10.5cm)
        canvas.drawString(center_x, 27*cm, header_text)
        canvas.setFont("Courier", 14)  # Reset to normal font
        
        # Create matplotlib figure for individual chart
        fig, ax = plt.subplots(figsize=(15/2.54, 15/2.54))  # Convert cm to inches for matplotlib
        
        # Plot the data for each location for this gas based on chart type
        color_idx = 0
        for location_data in locations_data:
            color = COLOUR_LIST[color_idx % len(COLOUR_LIST)]
            label = f"{location_data['location_label']} - {get_gas_display_name(gas_code)}"
            
            if chart_type == 'bar':
                # Convert timestamps to numeric format for bar chart
                numeric_times = mdates.date2num(location_data['timestamps'])
                
                # For bar charts when multiple locations are plotting at the same time points, 
                # we need to create grouped bars for each time point
                # Calculate the total number of bars at each time point
                total_bars_per_time = len(locations_data)  # One for each location
                max_elements_in_any_group = len(locations_data)  # All locations
                total_time_points = len(location_data['timestamps']) if 'timestamps' in location_data else 1
                
                # Use the shared function for consistent bar width calculation based on time interval
                # Calculate time interval from the data - use the interval passed to the function
                bar_width, offsets = calculate_grouped_bar_positions_and_widths(
                    interval, total_bars_per_time, max_elements_in_any_group, total_time_points
                )
                
                if total_bars_per_time > 1:
                    # Calculate positions using the shared function
                    start_offset = offsets[color_idx] if color_idx < len(offsets) else 0
                    
                    ax.bar(numeric_times + start_offset, location_data['averages'], 
                           width=bar_width, label=label, color=color, alpha=0.7)
                else:
                    # If only one location, use calculated width
                    ax.bar(numeric_times, location_data['averages'], 
                           width=bar_width, label=label, color=color, alpha=0.7)
                
                # Set the x-axis to show dates properly
                ax.xaxis_date()
            else:  # Default to line chart
                ax.plot(location_data['timestamps'], location_data['averages'], 
                       label=label, color=color, marker='o', markersize=4)
            color_idx += 1
        
        # Add threshold as a horizontal line if enabled
        show_threshold = report_options.get('individualChartWithThreshold', True)
        if show_threshold and gas_code in thresholds:
            threshold_value = thresholds[gas_code]
            ax.axhline(y=threshold_value, color='red', linestyle='--', linewidth=2, 
                      label=f'Threshold: {threshold_value}')
        
        ax.set_xlabel('Time')
        ax.set_ylabel('Average Reading')
        

        
        # Add legend to show all locations
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        
        ax.grid(True, linestyle='--', alpha=0.6)
        
        # Format x-axis dates to show the entire time period with sensible ticks
        ax.set_xlim(start_date, end_date)  # Set x-axis limits to the full time period
        set_x_axis_format(ax, start_date, end_date)
        
        # Save the plot to a temporary file
        chart_path = os.path.join(settings.STATICFILES_DIRS[0], f"gas_chart_{gas_code}.png") if hasattr(settings, 'STATICFILES_DIRS') and settings.STATICFILES_DIRS else f"/tmp/gas_chart_{gas_code}.png"
        plt.savefig(chart_path, format="png", bbox_inches="tight", dpi=150)
        plt.close()
        
        # Draw the chart on the PDF
        if os.path.exists(chart_path):
            # Position the chart below the header
            canvas.drawImage(chart_path, 1*cm, 8*cm, width=19*cm, height=16*cm)
        else:
            canvas.drawString(5*cm, 20*cm, "Error generating chart")
        
        close_page(canvas, header_string, generation_datetime)


def draw_summary_charts(canvas, start_date, end_date, interval, selected_locations, selected_gases, header_string, generation_datetime=None, show_threshold=True):
    """
    Draws summary charts grouped by gas for the PDF report
    Calculates overall averages for each location-gas combination similar to the summary table
    """
    from .models import SensorReading, Location, Sensor
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import matplotlib.colors as mcolors
    from collections import defaultdict
    import numpy as np
    from datetime import timedelta
    import os
    from django.conf import settings
    from django.db.models import Avg

    # Build the queryset with filters
    queryset = SensorReading.objects.filter(
        validation__isnull=True  # Only include valid readings
    ).select_related('sensor', 'location', 'location__job')
    
    # Apply date range filter
    queryset = queryset.filter(
        log_time__gt=start_date,
        log_time__lte=end_date
    )
    
    # Apply location filter if specified
    if selected_locations:
        queryset = queryset.filter(location_id__in=selected_locations)
    
    # Apply gas filter if specified
    if selected_gases:
        queryset = queryset.filter(sensor__gas_code__in=selected_gases)
    
    if not queryset.exists():
        canvas.drawString(5*cm, 25*cm, "No data available for the selected criteria")
        close_page(canvas, header_string, generation_datetime)
        return

    # Calculate the overall average for each location-gas combination (like in drawSummaryTable)
    location_gas_averages = queryset.values('location__label', 'sensor__gas_code').annotate(
        avg_reading=Avg('reading')
    ).order_by('location__label', 'sensor__gas_code')

    # Group the averages by gas
    data_by_gas = defaultdict(list)
    for result in location_gas_averages:
        gas_code = result['sensor__gas_code']
        location_label = result['location__label']
        avg_value = result['avg_reading']
        
        data_by_gas[gas_code].append({
            'location_label': location_label,
            'avg_value': avg_value
        })

    # Get default thresholds (same as in the frontend)
    thresholds = {
        'CO': 50.0,  # Carbon Monoxide
        'HS': 10.0,  # Hydrogen Sulfide
        'LE': 5.0,   # LEL (Lower Explosive Limit)
        'O2': 19.5,  # Oxygen
        'VO': 50.0   # VOC (Volatile Organic Compounds)
    }
    
    # Define color list
    COLOUR_LIST = [
        mcolors.CSS4_COLORS["blue"],
        mcolors.CSS4_COLORS["orange"],
        mcolors.CSS4_COLORS["green"],
        mcolors.CSS4_COLORS["red"],
        mcolors.CSS4_COLORS["brown"],
        mcolors.CSS4_COLORS["pink"],
        mcolors.CSS4_COLORS["gray"],
        mcolors.CSS4_COLORS["olive"],
        mcolors.CSS4_COLORS["cyan"],
    ]

    # Draw a chart for each gas showing all locations for that gas
    for gas_code, location_data_list in data_by_gas.items():
        # Add the header for this chart
        canvas.setFont("Courier-Bold", 14)  # Use bold font for header
        # Calculate center position for the header
        header_text = f"Summary Chart - {get_gas_display_name(gas_code)} Average Readings by Location"
        text_width = canvas.stringWidth(header_text, "Courier-Bold", 14)
        center_x = 10.5*cm - text_width/2  # Center of A4 page (21cm/2 = 10.5cm)
        canvas.drawString(center_x, 27*cm, header_text)
        canvas.setFont("Courier", 14)  # Reset to normal font
        
        # Create matplotlib figure for summary chart
        fig, ax = plt.subplots(figsize=(15/2.54, 15/2.54))  # Convert cm to inches for matplotlib
        
        # Extract location labels and average values
        locations = [data['location_label'] for data in location_data_list]
        avg_values = [data['avg_value'] for data in location_data_list]
        
        # Create bar chart with one bar per location
        colors = [COLOUR_LIST[i % len(COLOUR_LIST)] for i in range(len(locations))]
        bars = ax.bar(locations, avg_values, color=colors, alpha=0.7)
        
        # Add threshold as a horizontal line if enabled
        if show_threshold and gas_code in thresholds:
            threshold_value = thresholds[gas_code]
            ax.axhline(y=threshold_value, color='red', linestyle='--', linewidth=2)
        
        ax.set_xlabel('Location')
        ax.set_ylabel('Average Reading')
        
        ax.grid(True, linestyle='--', alpha=0.6)
        
        # Rotate x-axis labels if there are many locations
        plt.xticks(rotation=45)

        # Save the plot to a temporary file
        chart_path = os.path.join(settings.STATICFILES_DIRS[0], f"summary_chart_{gas_code}.png") if hasattr(settings, 'STATICFILES_DIRS') and settings.STATICFILES_DIRS else f"/tmp/summary_chart_{gas_code}.png"
        plt.savefig(chart_path, format="png", bbox_inches="tight", dpi=150)
        plt.close()
        
        # Draw the chart on the PDF
        if os.path.exists(chart_path):
            # Position the chart below the header
            canvas.drawImage(chart_path, 1*cm, 8*cm, width=19*cm, height=16*cm)
        else:
            canvas.drawString(5*cm, 20*cm, "Error generating chart")
        
        close_page(canvas, header_string)


def draw_title_page(canvas, job_label, address, start_date, stop_date, interval, generation_datetime):
    """
    Draws a title page with job information
    """
    # Set title page content
    canvas.setFont("Courier-Bold", 24)  # Use bold font for main title
    canvas.drawCentredString(10.5*cm, 25*cm, "FRV Hazmat Air Monitoring Report")
    
    canvas.setFont("Courier-Bold", 18)  # Use bold font for job title
    canvas.drawCentredString(10.5*cm, 22*cm, f"Job: {job_label}")
    
    canvas.setFont("Courier-Bold", 14)  # Use bold font for address
    canvas.drawCentredString(10.5*cm, 19*cm, f"Address: {address}")
    
    canvas.setFont("Courier-Bold", 12)  # Use bold font for date/time info
    canvas.drawCentredString(10.5*cm, 16*cm, f"Start Date: {start_date.strftime('%Y-%m-%d %H:%M') if start_date else 'N/A'}")
    canvas.drawCentredString(10.5*cm, 14*cm, f"Stop Date: {stop_date.strftime('%Y-%m-%d %H:%M') if stop_date else 'N/A'}")
    canvas.drawCentredString(10.5*cm, 12*cm, f"Interval: {interval} minutes")
    
    # Add the report generation time
    canvas.drawCentredString(10.5*cm, 10*cm, f"Generated: {generation_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    
    canvas.setFont("Courier", 12)  # Reset to normal font
    
    canvas.showPage()


def close_page(canvas, header_string, generation_datetime=None):
    """
    Handles page breaks in the PDF
    """
    canvas.setFont("Courier", 10)
    canvas.drawString(2*cm, 0.7*cm,"FRV Hazmat Air Monitoring Report")
    canvas.drawString(2*cm, 0.3*cm, header_string)
    
    # Add generation time to footer if available
    if generation_datetime:
        canvas.drawRightString(19*cm, 0.7*cm, f"Generated: {generation_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    
    canvas.showPage()

