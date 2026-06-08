"""
ECharts Formatters Module for Events

This module provides transformation functions to convert raw event statistical data
into ECharts-compatible configuration objects.

Reuses formatting functions from attendee app where applicable and adds
event-specific formatters.
"""
from typing import Dict, List, Any, Optional

# Import base formatters from attendee app to reuse
from apps.attendee.services.formatters import (
    format_pie_chart,
    format_donut_chart,
    format_bar_chart,
    format_line_chart,
    format_gauge_chart,
    add_toolbox,
    DEFAULT_COLORS
)


# Event-specific color schemes
REVENUE_COLORS = ['#5470c6', '#91cc75', '#fac858']
STATUS_COLORS = {
    'DRAFTING': '#909399',
    'PUBLISHED': '#409EFF',
    'OPEN': '#67C23A',
    'IN_PROGRESS': '#E6A23C',
    'COMPLETED': '#909399',
    'CLOSED': '#F56C6C',
    'CANCELLED': '#F56C6C',
    'POSTPONED': '#E6A23C',
}


def format_revenue_breakdown_chart(
    data: List[Dict[str, Any]],
    title: str = 'Revenue Breakdown',
    subtitle: Optional[str] = None
) -> Dict[str, Any]:
    """
    Format revenue breakdown data with custom colors.
    
    Args:
        data: List of dicts with 'source' and 'value' keys
        title: Chart title
        subtitle: Optional subtitle
    
    Returns:
        ECharts pie chart configuration with revenue colors
    """
    # Transform source to label
    formatted_data = [
        {'label': item['source'], 'value': item['value']}
        for item in data if item['value'] > 0  # Only show non-zero sources
    ]
    
    config = format_pie_chart(formatted_data, title, subtitle)
    config['color'] = REVENUE_COLORS
    
    # Add currency formatter
    config['tooltip']['formatter'] = '{a} <br/>{b}: ${c} ({d}%)'
    config['series'][0]['label']['formatter'] = '{b}: ${c}'
    
    return config


def format_revenue_bar_chart(
    data: List[Dict[str, Any]],
    title: str = 'Revenue by Event',
    show_multiple: bool = False
) -> Dict[str, Any]:
    """
    Format event revenue data as bar chart.
    
    Args:
        data: List of dicts with event revenue data
        title: Chart title
        show_multiple: Whether to show revenue breakdown (bookings, products, donations)
    
    Returns:
        ECharts bar chart or stacked bar chart configuration
    """
    if not show_multiple:
        # Simple bar chart with total revenue
        chart_data = [
            {
                'label': item['title'][:30] + '...' if len(item['title']) > 30 else item['title'],
                'value': item['total_revenue']
            }
            for item in data[:15]  # Top 15 events
        ]
        
        config = format_bar_chart(
            data=chart_data,
            title=title,
            x_axis_label='Event',
            y_axis_label='Revenue ($)',
            orientation='horizontal'
        )
        
        # Add currency formatting
        config['tooltip']['formatter'] = '{a} <br/>{b}: ${c}'
        config['yAxis']['axisLabel'] = {'formatter': '${value}'}
        
    else:
        # Stacked bar chart showing revenue sources
        categories = [
            item['title'][:30] + '...' if len(item['title']) > 30 else item['title']
            for item in data[:10]  # Top 10 events
        ]
        
        config = {
            'title': {
                'text': title,
                'left': 'center'
            },
            'tooltip': {
                'trigger': 'axis',
                'axisPointer': {'type': 'shadow'},
                'formatter': '{b}<br/>Total: ${c}'
            },
            'legend': {
                'data': ['Bookings', 'Products', 'Donations'],
                'top': 30
            },
            'grid': {
                'left': '3%',
                'right': '4%',
                'bottom': '3%',
                'containLabel': True
            },
            'xAxis': {
                'type': 'value',
                'name': 'Revenue ($)',
                'axisLabel': {'formatter': '${value}'}
            },
            'yAxis': {
                'type': 'category',
                'data': categories
            },
            'color': REVENUE_COLORS,
            'series': [
                {
                    'name': 'Bookings',
                    'type': 'bar',
                    'stack': 'total',
                    'data': [item['booking_revenue'] for item in data[:10]],
                    'emphasis': {'focus': 'series'}
                },
                {
                    'name': 'Products',
                    'type': 'bar',
                    'stack': 'total',
                    'data': [item['product_revenue'] for item in data[:10]],
                    'emphasis': {'focus': 'series'}
                },
                {
                    'name': 'Donations',
                    'type': 'bar',
                    'stack': 'total',
                    'data': [item['donation_revenue'] for item in data[:10]],
                    'emphasis': {'focus': 'series'}
                }
            ]
        }
    
    return config


def format_status_distribution_chart(
    data: List[Dict[str, Any]],
    title: str = 'Event Status Distribution'
) -> Dict[str, Any]:
    """
    Format event status distribution with custom status colors.
    
    Args:
        data: List of dicts with 'label', 'code', and 'value' keys
        title: Chart title
    
    Returns:
        ECharts donut chart configuration with status colors
    """
    config = format_donut_chart(
        data=data,
        title=title,
        center_text=f"{sum(item['value'] for item in data)}\nTotal Events"
    )
    
    # Apply status-specific colors
    series_data = config['series'][0]['data']
    for item in series_data:
        # Find matching data to get code
        matching = next((d for d in data if d['label'] == item['name']), None)
        if matching and matching.get('code') in STATUS_COLORS:
            item['itemStyle'] = {'color': STATUS_COLORS[matching['code']]}
    
    return config


def format_capacity_utilization_chart(
    data: List[Dict[str, Any]],
    title: str = 'Capacity Utilization'
) -> Dict[str, Any]:
    """
    Format capacity utilization data as horizontal bar chart.
    
    Args:
        data: List of dicts with event capacity data
        title: Chart title
    
    Returns:
        ECharts bar chart configuration
    """
    # Sort by utilization and take top 15
    sorted_data = sorted(data, key=lambda x: x['utilization_percentage'], reverse=True)[:15]
    
    categories = [
        item['title'][:30] + '...' if len(item['title']) > 30 else item['title']
        for item in sorted_data
    ]
    
    config = {
        'title': {
            'text': title,
            'left': 'center'
        },
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {'type': 'shadow'},
            'formatter': '{b}<br/>Utilization: {c}%<br/>Registered: {a}'
        },
        'grid': {
            'left': '3%',
            'right': '4%',
            'bottom': '3%',
            'containLabel': True
        },
        'xAxis': {
            'type': 'value',
            'name': 'Utilization (%)',
            'max': 100,
            'axisLabel': {'formatter': '{value}%'}
        },
        'yAxis': {
            'type': 'category',
            'data': categories
        },
        'series': [
            {
                'name': 'Registered',
                'type': 'bar',
                'data': [
                    {
                        'value': item['utilization_percentage'],
                        'itemStyle': {
                            'color': '#67C23A' if item['utilization_percentage'] < 80
                            else '#E6A23C' if item['utilization_percentage'] < 95
                            else '#F56C6C'
                        }
                    }
                    for item in sorted_data
                ],
                'emphasis': {'focus': 'series'},
                'label': {
                    'show': True,
                    'position': 'right',
                    'formatter': '{c}%'
                }
            }
        ]
    }
    
    return config


def format_rating_distribution_chart(
    data: List[Dict[str, Any]],
    title: str = 'Rating Distribution',
    average_rating: Optional[float] = None
) -> Dict[str, Any]:
    """
    Format rating distribution as bar chart.
    
    Args:
        data: List of dicts with 'rating' and 'count' keys
        title: Chart title
        average_rating: Optional average rating to display
    
    Returns:
        ECharts bar chart configuration
    """
    # Ensure all ratings 1-5 are represented
    rating_counts = {item['rating']: item['count'] for item in data}
    full_data = [
        {'label': f"{i} Star{'s' if i > 1 else ''}", 'value': rating_counts.get(i, 0)}
        for i in range(1, 6)
    ]
    
    config = format_bar_chart(
        data=full_data,
        title=title,
        x_axis_label='Rating',
        y_axis_label='Count'
    )
    
    # Add average rating subtitle if provided
    if average_rating:
        config['title']['subtext'] = f"Average: {average_rating:.1f} / 5.0"
    
    # Color bars by rating (low=red, high=green)
    rating_colors = ['#F56C6C', '#E6A23C', '#E6A23C', '#67C23A', '#67C23A']
    config['series'][0]['data'] = [
        {
            'value': full_data[i]['value'],
            'itemStyle': {'color': rating_colors[i]}
        }
        for i in range(5)
    ]
    
    return config


def format_event_timeline_chart(
    data: List[Dict[str, Any]],
    title: str = 'Upcoming Events Timeline'
) -> Dict[str, Any]:
    """
    Format upcoming events as timeline/calendar view.
    
    Args:
        data: List of dicts with event date and title
        title: Chart title
    
    Returns:
        ECharts calendar/scatter configuration
    """
    # Group events by date
    from collections import defaultdict
    events_by_date = defaultdict(list)
    
    for event in data:
        date = event['start_datetime'][:10]  # YYYY-MM-DD
        events_by_date[date].append(event['title'])
    
    # Create scatter data
    scatter_data = []
    for date, titles in events_by_date.items():
        scatter_data.append([date, len(titles)])
    
    config = {
        'title': {
            'text': title,
            'left': 'center'
        },
        'tooltip': {
            'position': 'top',
            'formatter': '{c0}: {c1} event(s)'
        },
        'visualMap': {
            'min': 1,
            'max': 10,
            'calculable': True,
            'orient': 'horizontal',
            'left': 'center',
            'bottom': 20,
            'inRange': {
                'color': ['#e0f3f8', '#abd9e9', '#74add1', '#4575b4', '#313695']
            }
        },
        'calendar': {
            'range': [min(events_by_date.keys()), max(events_by_date.keys())],
            'cellSize': ['auto', 20]
        },
        'series': [
            {
                'type': 'heatmap',
                'coordinateSystem': 'calendar',
                'data': scatter_data
            }
        ]
    }
    
    return config


def format_payment_status_chart(
    data: List[Dict[str, Any]],
    title: str = 'Payment Status Distribution'
) -> Dict[str, Any]:
    """
    Format payment status distribution.
    
    Args:
        data: List of dicts with 'label', 'count', and 'amount' keys
        title: Chart title
    
    Returns:
        ECharts configuration with dual display (count and amount)
    """
    config = {
        'title': {
            'text': title,
            'left': 'center'
        },
        'tooltip': {
            'trigger': 'item',
            'formatter': '{a} <br/>{b}: {c} bookings (${d})'
        },
        'legend': {
            'orient': 'vertical',
            'left': 'left',
            'data': [item['label'] for item in data]
        },
        'color': DEFAULT_COLORS,
        'series': [
            {
                'name': 'Payment Status',
                'type': 'pie',
                'radius': ['40%', '70%'],
                'avoidLabelOverlap': False,
                'data': [
                    {
                        'name': item['label'],
                        'value': item['count']
                    }
                    for item in data
                ],
                'emphasis': {
                    'itemStyle': {
                        'shadowBlur': 10,
                        'shadowOffsetX': 0,
                        'shadowColor': 'rgba(0, 0, 0, 0.5)'
                    }
                },
                'label': {
                    'formatter': '{b}: {d}%'
                }
            }
        ]
    }
    
    return config


def format_staff_allocation_chart(
    data: List[Dict[str, Any]],
    title: str = 'Staff per Event'
) -> Dict[str, Any]:
    """
    Format staff allocation data.
    
    Args:
        data: List of dicts with event and staff count
        title: Chart title
    
    Returns:
        ECharts bar chart configuration
    """
    chart_data = [
        {
            'label': item['event_title'][:30] + '...' if len(item['event_title']) > 30 else item['event_title'],
            'value': item['staff_count']
        }
        for item in data[:15]
    ]
    
    config = format_bar_chart(
        data=chart_data,
        title=title,
        x_axis_label='Event',
        y_axis_label='Staff Count',
        orientation='horizontal'
    )
    
    return config


def format_booking_package_chart(
    data: List[Dict[str, Any]],
    title: str = 'Booking Package Performance'
) -> Dict[str, Any]:
    """
    Format booking package performance data.
    
    Args:
        data: List of dicts with package data
        title: Chart title
    
    Returns:
        ECharts configuration showing bookings and revenue
    """
    # Sort by bookings and take top 10
    sorted_data = sorted(data, key=lambda x: x['bookings'], reverse=True)[:10]
    
    categories = [
        f"{item['package_name']} ({item['event_title'][:20]}...)" if len(item['event_title']) > 20
        else f"{item['package_name']} ({item['event_title']})"
        for item in sorted_data
    ]
    
    config = {
        'title': {
            'text': title,
            'left': 'center'
        },
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {'type': 'cross'}
        },
        'legend': {
            'data': ['Bookings', 'Revenue'],
            'top': 30
        },
        'grid': {
            'left': '3%',
            'right': '4%',
            'bottom': '3%',
            'containLabel': True
        },
        'xAxis': {
            'type': 'category',
            'data': categories,
            'axisLabel': {
                'rotate': 45,
                'interval': 0
            }
        },
        'yAxis': [
            {
                'type': 'value',
                'name': 'Bookings',
                'position': 'left'
            },
            {
                'type': 'value',
                'name': 'Revenue ($)',
                'position': 'right',
                'axisLabel': {'formatter': '${value}'}
            }
        ],
        'series': [
            {
                'name': 'Bookings',
                'type': 'bar',
                'data': [item['bookings'] for item in sorted_data],
                'emphasis': {'focus': 'series'}
            },
            {
                'name': 'Revenue',
                'type': 'line',
                'yAxisIndex': 1,
                'data': [item['revenue'] for item in sorted_data],
                'emphasis': {'focus': 'series'}
            }
        ]
    }
    
    return config
