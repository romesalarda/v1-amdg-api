# Attendee Statistics API - Quick Reference

## Overview

The attendee statistics system provides comprehensive analytics for attendee data with support for both raw JSON and ECharts-ready formats.

**Base URL:** `/api/attendees/statistics/`

## Endpoints

### Dashboard Overview
```
GET /api/attendees/statistics/overview/
```
Combined statistics ideal for dashboard display.

### Demographics
```
GET /api/attendees/statistics/demographics/
GET /api/attendees/statistics/age-distribution/
GET /api/attendees/statistics/gender-distribution/
GET /api/attendees/statistics/relationship-distribution/
GET /api/attendees/statistics/area-distribution/
```

### Personal Information
```
GET /api/attendees/statistics/personal-info/
GET /api/attendees/statistics/medical-conditions/
GET /api/attendees/statistics/accessibility/
GET /api/attendees/statistics/dietary/
GET /api/attendees/statistics/emergency-contacts/
```

### Consents & Attendance
```
GET /api/attendees/statistics/consents/
GET /api/attendees/statistics/registration-trends/
GET /api/attendees/statistics/attendance/
```

## Query Parameters

### Common Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `format` | string | Response format: `raw` or `echarts` | `raw` |
| `event_id` | UUID | Filter to specific event | None (global) |
| `include_deleted` | boolean | Include soft-deleted attendees | `false` |

### Endpoint-Specific Parameters

**Age Distribution:**
- `age_grouping`: `ranges` or `individual` (default: `ranges`)

**Registration Trends:**
- `group_by`: `day`, `week`, or `month` (default: `day`)
- `date_from`: Start date (YYYY-MM-DD)
- `date_to`: End date (YYYY-MM-DD)

## Response Formats

### Raw Format (Default)

```json
{
  "total_with_age": 150,
  "total_without_age": 10,
  "average_age": 32.5,
  "distribution": [
    {"label": "18-25", "value": 45, "percentage": 30.0},
    {"label": "26-35", "value": 60, "percentage": 40.0}
  ],
  "generated_at": "2026-03-09T12:00:00Z",
  "filters_applied": {"event_id": "some-uuid"}
}
```

### ECharts Format

When `format=echarts`, the response includes a `chart` field with ECharts configuration:

```json
{
  "total_with_age": 150,
  "distribution": [...],
  "chart": {
    "title": {"text": "Age Distribution"},
    "tooltip": {...},
    "xAxis": {...},
    "yAxis": {...},
    "series": [...]
  }
}
```

## Example Requests

### Get Gender Distribution for Specific Event
```bash
curl "http://localhost:8000/api/attendees/statistics/gender-distribution/?event_id=abc-123&format=echarts"
```

### Get Age Distribution with Individual Ages
```bash
curl "http://localhost:8000/api/attendees/statistics/age-distribution/?age_grouping=individual"
```

### Get Registration Trends by Week
```bash
curl "http://localhost:8000/api/attendees/statistics/registration-trends/?group_by=week&date_from=2026-01-01&date_to=2026-03-01"
```

## Frontend Integration (Vue.js + ECharts)

```vue
<template>
  <v-chart :option="chartOption" autoresize />
</template>

<script setup>
import { ref, onMounted } from 'vue'
import VChart from 'vue-echarts'

const chartOption = ref({})

onMounted(async () => {
  const response = await fetch(
    '/api/attendees/statistics/age-distribution/?format=echarts&event_id=abc-123'
  )
  const data = await response.json()
  chartOption.value = data.chart
})
</script>
```

## Architecture

### File Structure
```
apps/attendee/
├── statistics.py              # Core calculation logic (ORM queries)
├── formatters.py              # ECharts transformation functions
├── api/
│   ├── statistics_viewset.py  # API endpoints and request handling
│   └── serializers/
│       └── statistics.py      # Response serialization with dual format support
```

### Design Principles

1. **Separation of Concerns**: 
   - Logic (statistics.py) separate from presentation (formatters.py)
   - Serializers handle format transformation based on context

2. **Efficient Queries**: 
   - Uses Django ORM aggregations (Count, Avg, annotate)
   - Single queries where possible, no N+1 problems

3. **Extensibility**: 
   - Easy to add new statistics functions
   - Easy to add new chart formatters
   - Format-agnostic core logic

4. **Testability**: 
   - Pure functions with clear inputs/outputs
   - Minimal dependencies between modules

## Notes

- All endpoints require authentication
- Consent statistics require `event_id` parameter (event-specific)
- Soft-deleted attendees are excluded by default
- ECharts configurations follow v5 API conventions
- Dates use ISO 8601 format (YYYY-MM-DD)

## Next Steps

1. **Caching**: Consider adding Redis/Django cache for expensive queries
2. **Pagination**: For detailed breakdowns with many items
3. **Export**: Add PDF/Excel export capabilities
4. **Real-time**: WebSocket updates for live dashboards
5. **Permissions**: Fine-grained access control (currently all authenticated)
