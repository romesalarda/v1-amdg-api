"""
ECharts Formatters Module

This module provides transformation functions to convert raw statistical data
into ECharts-compatible configuration objects.

Each formatter follows ECharts v5 API conventions and returns:
- Complete chart configuration (tooltip, legend, series, axis, etc.)
- Responsive design considerations
- Proper color schemes and styling
"""
from typing import Dict, List, Any, Optional


# ============================================================================
# CHART COLOR SCHEMES
# ============================================================================

DEFAULT_COLORS = [
    '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
    '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#d4a4eb'
]

SEVERITY_COLORS = {
    'mild': '#91cc75',      # Green
    'moderate': '#fac858',  # Yellow
    'severe': '#ee6666',    # Red
}


# ============================================================================
# PIE CHART FORMATTERS
# ============================================================================

def format_pie_chart(
    data: List[Dict[str, Any]],
    title: str,
    subtitle: Optional[str] = None
) -> Dict[str, Any]:
    """
    Format data for ECharts pie chart.
    
    Args:
        data: List of dicts with 'label' and 'value' keys
        title: Chart title
        subtitle: Optional subtitle
    
    Returns:
        ECharts pie chart configuration
    """
    series_data = [
        {'name': item['label'], 'value': item['value']}
        for item in data
    ]
    
    config = {
        'title': {
            'text': title,
            'subtext': subtitle or '',
            'left': 'center'
        },
        'tooltip': {
            'trigger': 'item',
            'formatter': '{a} <br/>{b}: {c} ({d}%)'
        },
        'legend': {
            'orient': 'vertical',
            'left': 'left',
            'data': [item['label'] for item in data]
        },
        'color': DEFAULT_COLORS,
        'series': [
            {
                'name': title,
                'type': 'pie',
                'radius': '50%',
                'data': series_data,
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


def format_donut_chart(
    data: List[Dict[str, Any]],
    title: str,
    subtitle: Optional[str] = None,
    center_text: Optional[str] = None
) -> Dict[str, Any]:
    """
    Format data for ECharts donut chart (pie with center hole).
    
    Args:
        data: List of dicts with 'label' and 'value' keys
        title: Chart title
        subtitle: Optional subtitle
        center_text: Text to display in center
    
    Returns:
        ECharts donut chart configuration
    """
    config = format_pie_chart(data, title, subtitle)
    
    # Modify to donut style
    config['series'][0]['radius'] = ['40%', '70%']
    config['series'][0]['avoidLabelOverlap'] = False
    config['series'][0]['label'] = {
        'show': False,
        'position': 'center'
    }
    config['series'][0]['emphasis'] = {
        'label': {
            'show': True,
            'fontSize': 20,
            'fontWeight': 'bold'
        }
    }
    config['series'][0]['labelLine'] = {
        'show': False
    }
    
    if center_text:
        config['graphic'] = {
            'type': 'text',
            'left': 'center',
            'top': 'center',
            'style': {
                'text': center_text,
                'textAlign': 'center',
                'fill': '#333',
                'fontSize': 16
            }
        }
    
    return config


# ============================================================================
# BAR CHART FORMATTERS
# ============================================================================

def format_bar_chart(
    data: List[Dict[str, Any]],
    title: str,
    x_axis_label: str = '',
    y_axis_label: str = 'Count',
    orientation: str = 'vertical'
) -> Dict[str, Any]:
    """
    Format data for ECharts bar chart.
    
    Args:
        data: List of dicts with 'label' and 'value' keys
        title: Chart title
        x_axis_label: X-axis label text
        y_axis_label: Y-axis label text
        orientation: 'vertical' or 'horizontal'
    
    Returns:
        ECharts bar chart configuration
    """
    categories = [item['label'] for item in data]
    values = [item['value'] for item in data]
    
    if orientation == 'horizontal':
        # Swap axes for horizontal bars
        x_axis = {
            'type': 'value',
            'name': y_axis_label,
            'nameLocation': 'middle',
            'nameGap': 30
        }
        y_axis = {
            'type': 'category',
            'data': categories,
            'name': x_axis_label
        }
    else:
        x_axis = {
            'type': 'category',
            'data': categories,
            'name': x_axis_label,
            'nameLocation': 'middle',
            'nameGap': 30,
            'axisLabel': {
                'rotate': 45 if len(categories) > 5 else 0
            }
        }
        y_axis = {
            'type': 'value',
            'name': y_axis_label,
            'nameLocation': 'middle',
            'nameGap': 40
        }
    
    config = {
        'title': {
            'text': title,
            'left': 'center'
        },
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {
                'type': 'shadow'
            }
        },
        'grid': {
            'left': '3%',
            'right': '4%',
            'bottom': '15%',
            'containLabel': True
        },
        'xAxis': x_axis,
        'yAxis': y_axis,
        'color': DEFAULT_COLORS,
        'series': [
            {
                'name': y_axis_label,
                'type': 'bar',
                'data': values,
                'emphasis': {
                    'focus': 'series'
                },
                'itemStyle': {
                    'borderRadius': [5, 5, 0, 0] if orientation == 'vertical' else [0, 5, 5, 0]
                }
            }
        ]
    }
    
    return config


def format_stacked_bar_chart(
    data: Dict[str, List[Dict[str, Any]]],
    title: str,
    x_axis_label: str = '',
    y_axis_label: str = 'Count'
) -> Dict[str, Any]:
    """
    Format data for ECharts stacked bar chart.
    
    Args:
        data: Dict with series names as keys and list of dicts with 'label' and 'value'
        title: Chart title
        x_axis_label: X-axis label text
        y_axis_label: Y-axis label text
    
    Returns:
        ECharts stacked bar chart configuration
    """
    # Get categories from first series
    first_series = next(iter(data.values()))
    categories = [item['label'] for item in first_series]
    
    series_list = []
    for series_name, series_data in data.items():
        series_list.append({
            'name': series_name,
            'type': 'bar',
            'stack': 'total',
            'data': [item['value'] for item in series_data],
            'emphasis': {
                'focus': 'series'
            }
        })
    
    config = {
        'title': {
            'text': title,
            'left': 'center'
        },
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {
                'type': 'shadow'
            }
        },
        'legend': {
            'data': list(data.keys()),
            'top': 30
        },
        'grid': {
            'left': '3%',
            'right': '4%',
            'bottom': '15%',
            'containLabel': True
        },
        'xAxis': {
            'type': 'category',
            'data': categories,
            'name': x_axis_label,
            'nameLocation': 'middle',
            'nameGap': 30
        },
        'yAxis': {
            'type': 'value',
            'name': y_axis_label,
            'nameLocation': 'middle',
            'nameGap': 40
        },
        'color': DEFAULT_COLORS,
        'series': series_list
    }
    
    return config


# ============================================================================
# LINE CHART FORMATTERS
# ============================================================================

def format_line_chart(
    data: List[Dict[str, Any]],
    title: str,
    x_axis_label: str = 'Date',
    y_axis_label: str = 'Count',
    smooth: bool = True
) -> Dict[str, Any]:
    """
    Format data for ECharts line chart (typically for time series).
    
    Args:
        data: List of dicts with 'date' and 'count' keys
        title: Chart title
        x_axis_label: X-axis label text
        y_axis_label: Y-axis label text
        smooth: Whether to smooth the line curve
    
    Returns:
        ECharts line chart configuration
    """
    dates = [item['date'] for item in data]
    values = [item['count'] for item in data]
    
    config = {
        'title': {
            'text': title,
            'left': 'center'
        },
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {
                'type': 'cross'
            }
        },
        'grid': {
            'left': '3%',
            'right': '4%',
            'bottom': '15%',
            'containLabel': True
        },
        'xAxis': {
            'type': 'category',
            'boundaryGap': False,
            'data': dates,
            'name': x_axis_label,
            'nameLocation': 'middle',
            'nameGap': 30
        },
        'yAxis': {
            'type': 'value',
            'name': y_axis_label,
            'nameLocation': 'middle',
            'nameGap': 40
        },
        'color': DEFAULT_COLORS,
        'series': [
            {
                'name': y_axis_label,
                'type': 'line',
                'data': values,
                'smooth': smooth,
                'areaStyle': {
                    'opacity': 0.3
                },
                'emphasis': {
                    'focus': 'series'
                }
            }
        ]
    }
    
    return config


def format_multi_line_chart(
    data: Dict[str, List[Dict[str, Any]]],
    title: str,
    x_axis_label: str = 'Date',
    y_axis_label: str = 'Count'
) -> Dict[str, Any]:
    """
    Format data for ECharts multi-line chart.
    
    Args:
        data: Dict with series names as keys and list of dicts with 'date' and 'count'
        title: Chart title
        x_axis_label: X-axis label text
        y_axis_label: Y-axis label text
    
    Returns:
        ECharts multi-line chart configuration
    """
    # Get dates from first series
    first_series = next(iter(data.values()))
    dates = [item['date'] for item in first_series]
    
    series_list = []
    for series_name, series_data in data.items():
        series_list.append({
            'name': series_name,
            'type': 'line',
            'data': [item['count'] for item in series_data],
            'smooth': True,
            'emphasis': {
                'focus': 'series'
            }
        })
    
    config = {
        'title': {
            'text': title,
            'left': 'center'
        },
        'tooltip': {
            'trigger': 'axis',
            'axisPointer': {
                'type': 'cross'
            }
        },
        'legend': {
            'data': list(data.keys()),
            'top': 30
        },
        'grid': {
            'left': '3%',
            'right': '4%',
            'bottom': '15%',
            'containLabel': True
        },
        'xAxis': {
            'type': 'category',
            'boundaryGap': False,
            'data': dates,
            'name': x_axis_label,
            'nameLocation': 'middle',
            'nameGap': 30
        },
        'yAxis': {
            'type': 'value',
            'name': y_axis_label,
            'nameLocation': 'middle',
            'nameGap': 40
        },
        'color': DEFAULT_COLORS,
        'series': series_list
    }
    
    return config


# ============================================================================
# SPECIALIZED FORMATTERS
# ============================================================================

def format_severity_pie_chart(data: List[Dict[str, Any]], title: str) -> Dict[str, Any]:
    """
    Format severity data with custom colors for pie chart.
    
    Args:
        data: List of dicts with 'label' and 'value' keys
        title: Chart title
    
    Returns:
        ECharts pie chart configuration with severity colors
    """
    config = format_pie_chart(data, title)
    
    # Apply severity colors
    series_data = config['series'][0]['data']
    for item in series_data:
        severity = item['name'].lower()
        if severity in SEVERITY_COLORS:
            item['itemStyle'] = {'color': SEVERITY_COLORS[severity]}
    
    return config


def format_gauge_chart(
    value: float,
    title: str,
    max_value: float = 100,
    unit: str = '%'
) -> Dict[str, Any]:
    """
    Format single value for ECharts gauge chart.
    
    Args:
        value: The numeric value to display
        title: Chart title
        max_value: Maximum value for the gauge
        unit: Unit suffix for the value
    
    Returns:
        ECharts gauge chart configuration
    """
    config = {
        'title': {
            'text': title,
            'left': 'center'
        },
        'series': [
            {
                'type': 'gauge',
                'progress': {
                    'show': True,
                    'width': 18
                },
                'axisLine': {
                    'lineStyle': {
                        'width': 18
                    }
                },
                'axisTick': {
                    'show': False
                },
                'splitLine': {
                    'length': 15,
                    'lineStyle': {
                        'width': 2,
                        'color': '#999'
                    }
                },
                'axisLabel': {
                    'distance': 25,
                    'color': '#999',
                    'fontSize': 14
                },
                'anchor': {
                    'show': True,
                    'showAbove': True,
                    'size': 25,
                    'itemStyle': {
                        'borderWidth': 10
                    }
                },
                'detail': {
                    'valueAnimation': True,
                    'formatter': f'{{value}}{unit}',
                    'color': 'auto',
                    'fontSize': 30,
                    'offsetCenter': [0, '70%']
                },
                'data': [
                    {
                        'value': round(value, 2),
                        'name': title
                    }
                ],
                'max': max_value
            }
        ]
    }
    
    return config


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def add_data_zoom(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add data zoom controls to a chart configuration.
    
    Args:
        config: Existing ECharts configuration
    
    Returns:
        Updated configuration with data zoom
    """
    config['dataZoom'] = [
        {
            'type': 'inside',
            'start': 0,
            'end': 100
        },
        {
            'start': 0,
            'end': 100
        }
    ]
    
    return config


def add_toolbox(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add toolbox with save, restore, and data view features.
    
    Args:
        config: Existing ECharts configuration
    
    Returns:
        Updated configuration with toolbox
    """
    config['toolbox'] = {
        'feature': {
            'saveAsImage': {'title': 'Save as Image'},
            'restore': {'title': 'Restore'},
            'dataView': {'title': 'Data View', 'readOnly': False},
            'magicType': {
                'type': ['line', 'bar'],
                'title': {'line': 'Line', 'bar': 'Bar'}
            }
        }
    }
    
    return config
