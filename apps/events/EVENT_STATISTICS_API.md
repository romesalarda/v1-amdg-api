# Event Statistics API Documentation

## Overview

The Event Statistics API provides comprehensive analytics for event-related data with dual format support:
- **Raw JSON format** (default): Structured data suitable for custom visualizations
- **ECharts format**: Pre-configured ECharts v5 chart configurations ready to render

## Base URL

```
/api/v1/events/event/statistics/
```

## Authentication

All endpoints require authentication via Bearer token.

## Common Parameters

All endpoints support the following query parameters:

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `format` | string | Response format: `raw` or `echarts` | `raw` |
| `event_id` | integer | Filter by specific event ID | - |
| `event_type_id` | integer | Filter by event type ID | - |
| `organization_id` | integer | Filter by organization ID | - |
| `status` | string | Filter by event status (DRAFTING, PUBLISHED, OPEN, IN_PROGRESS, COMPLETED, CLOSED, CANCELLED, POSTPONED) | - |
| `date_from` | date | Start date for filtering (YYYY-MM-DD) | - |
| `date_to` | date | End date for filtering (YYYY-MM-DD) | - |

## Endpoints

### 1. Overview Statistics

Get comprehensive dashboard-style overview of all event statistics.

**Endpoint:** `GET /api/v1/events/event/statistics/overview/`

**Response (Raw Format):**
```json
{
  "total_events": 45,
  "active_events": 12,
  "upcoming_events": 8,
  "completed_events": 20,
  "total_revenue": "125000.00",
  "total_bookings": 450,
  "total_attendees": 389,
  "average_capacity_utilization": 78.5,
  "average_rating": 4.3,
  "total_reviews": 67,
  "filters_applied": {
    "organization_id": 1
  }
}
```

**Example Request:**
```bash
curl -X GET "https://api.example.com/api/v1/events/event/statistics/overview/?organization_id=1&format=raw" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

### 2. Status Distribution

Get distribution of events across different statuses.

**Endpoint:** `GET /api/v1/events/event/statistics/status-distribution/`

**Response (Raw Format):**
```json
{
  "distribution": [
    {
      "label": "Open",
      "code": "OPEN",
      "value": 15,
      "percentage": 33.3
    },
    {
      "label": "Published",
      "code": "PUBLISHED",
      "value": 10,
      "percentage": 22.2
    },
    {
      "label": "Completed",
      "code": "COMPLETED",
      "value": 20,
      "percentage": 44.4
    }
  ],
  "total_events": 45
}
```

**Response (ECharts Format):**
Returns a donut chart configuration with status-specific colors.

---

### 3. Type Distribution

Get distribution of events by type.

**Endpoint:** `GET /api/v1/events/event/statistics/type-distribution/`

**Response (Raw Format):**
```json
{
  "distribution": [
    {
      "label": "Workshop",
      "value": 20,
      "percentage": 44.4
    },
    {
      "label": "Conference",
      "value": 15,
      "percentage": 33.3
    },
    {
      "label": "Seminar",
      "value": 10,
      "percentage": 22.2
    }
  ],
  "total_events": 45
}
```

**Response (ECharts Format):**
Returns a pie chart configuration.

---

### 4. Organization Distribution

Get distribution of events by organization.

**Endpoint:** `GET /api/v1/events/event/statistics/organization-distribution/`

**Additional Parameters:**
- `limit` (integer): Maximum number of organizations to return (default: 10)

**Response (Raw Format):**
```json
{
  "distribution": [
    {
      "label": "Organization A",
      "value": 25,
      "percentage": 55.6
    },
    {
      "label": "Organization B",
      "value": 20,
      "percentage": 44.4
    }
  ],
  "total_events": 45
}
```

---

### 5. Upcoming Events

Get list of upcoming events within specified timeframe.

**Endpoint:** `GET /api/v1/events/event/statistics/upcoming/`

**Additional Parameters:**
- `days_ahead` (integer): Number of days ahead to consider (default: 30)

**Response (Raw Format):**
```json
{
  "events": [
    {
      "id": 1,
      "title": "Spring Workshop",
      "start_datetime": "2024-03-15T10:00:00Z",
      "end_datetime": "2024-03-15T16:00:00Z",
      "type": "Workshop",
      "status": "OPEN",
      "registered_count": 35,
      "maximum_attendance": 50
    }
  ],
  "total_upcoming": 8,
  "date_range": {
    "from": "2024-03-01",
    "to": "2024-03-31"
  }
}
```

**Response (ECharts Format):**
Returns a calendar heatmap showing event concentration.

---

### 6. Revenue Overview

Get comprehensive revenue overview with breakdown by source.

**Endpoint:** `GET /api/v1/events/event/statistics/revenue-overview/`

**Response (Raw Format):**
```json
{
  "total_revenue": "125000.00",
  "booking_revenue": "95000.00",
  "product_revenue": "20000.00",
  "donation_revenue": "10000.00",
  "breakdown": [
    {"source": "Bookings", "value": 95000.00},
    {"source": "Products", "value": 20000.00},
    {"source": "Donations", "value": 10000.00}
  ]
}
```

**Response (ECharts Format):**
Returns a pie chart with revenue breakdown and currency formatting.

---

### 7. Revenue by Event

Get revenue data for each event with optional breakdown by source.

**Endpoint:** `GET /api/v1/events/event/statistics/revenue-by-event/`

**Additional Parameters:**
- `limit` (integer): Maximum number of events to return (default: 15)
- `sort_by` (string): Sort field - `total_revenue`, `booking_revenue`, `product_revenue` (default: `total_revenue`)
- `show_breakdown` (boolean): Show revenue breakdown by source (default: false)

**Response (Raw Format):**
```json
{
  "events": [
    {
      "event_id": 1,
      "title": "Spring Conference",
      "total_revenue": 45000.00,
      "booking_revenue": 40000.00,
      "product_revenue": 3000.00,
      "donation_revenue": 2000.00
    }
  ],
  "total_events": 45
}
```

**Response (ECharts Format with breakdown):**
Returns a stacked horizontal bar chart showing revenue sources.

---

### 8. Payment Status Distribution

Get distribution of booking payment statuses.

**Endpoint:** `GET /api/v1/events/event/statistics/payment-status/`

**Response (Raw Format):**
```json
{
  "distribution": [
    {
      "label": "Paid",
      "count": 350,
      "amount": "87500.00",
      "percentage": 77.8
    },
    {
      "label": "Pending",
      "count": 80,
      "amount": "20000.00",
      "percentage": 17.8
    },
    {
      "label": "Failed",
      "count": 20,
      "amount": "5000.00",
      "percentage": 4.4
    }
  ],
  "total_bookings": 450,
  "total_amount": "112500.00"
}
```

---

### 9. Capacity Utilization

Get capacity utilization showing registered vs maximum attendance.

**Endpoint:** `GET /api/v1/events/event/statistics/capacity-utilization/`

**Response (Raw Format):**
```json
{
  "events": [
    {
      "event_id": 1,
      "title": "Spring Workshop",
      "registered_count": 45,
      "maximum_attendance": 50,
      "utilization_percentage": 90.0
    }
  ],
  "average_utilization": 78.5
}
```

**Response (ECharts Format):**
Returns a horizontal bar chart with color-coded utilization (green < 80%, yellow < 95%, red >= 95%).

---

### 10. Registration Trends

Get registration trends over time.

**Endpoint:** `GET /api/v1/events/event/statistics/registration-trends/`

**Additional Parameters:**
- `period` (string): Time period grouping - `day`, `week`, `month` (default: `month`)
- `cumulative` (boolean): Include cumulative data (default: false)

**Response (Raw Format):**
```json
{
  "trends": [
    {
      "period": "2024-01",
      "count": 45,
      "cumulative": 45
    },
    {
      "period": "2024-02",
      "count": 52,
      "cumulative": 97
    }
  ],
  "total_registrations": 450,
  "period": "month"
}
```

**Response (ECharts Format with cumulative):**
Returns a multi-line chart showing both new and cumulative registrations.

---

### 11. Review Statistics

Get event review statistics including ratings distribution.

**Endpoint:** `GET /api/v1/events/event/statistics/reviews/`

**Additional Parameters:**
- `limit` (integer): Maximum number of top-rated events to return (default: 10)

**Response (Raw Format):**
```json
{
  "total_reviews": 89,
  "average_rating": 4.3,
  "rating_distribution": [
    {"rating": 5, "count": 45},
    {"rating": 4, "count": 30},
    {"rating": 3, "count": 10},
    {"rating": 2, "count": 3},
    {"rating": 1, "count": 1}
  ],
  "approval_status": {
    "approved": 80,
    "pending": 9
  },
  "top_rated_events": [
    {
      "event_id": 5,
      "title": "Advanced Workshop",
      "average_rating": 4.8,
      "review_count": 15
    }
  ]
}
```

**Response (ECharts Format):**
Returns a bar chart with 1-5 star rating distribution, color-coded by rating.

---

### 12. Staff Allocation

Get staff allocation data showing staff distribution across events.

**Endpoint:** `GET /api/v1/events/event/statistics/staff-allocation/`

**Additional Parameters:**
- `limit` (integer): Maximum number of events to return (default: 10)

**Response (Raw Format):**
```json
{
  "events": [
    {
      "event_id": 1,
      "event_title": "Spring Conference",
      "staff_count": 12
    }
  ],
  "total_staff_assignments": 145,
  "average_staff_per_event": 3.2,
  "most_active_staff": [
    {
      "staff_id": 5,
      "staff_name": "John Doe",
      "event_count": 8
    }
  ]
}
```

---

### 13. Booking Package Performance

Get performance statistics for booking packages.

**Endpoint:** `GET /api/v1/events/event/statistics/booking-packages/`

**Additional Parameters:**
- `limit` (integer): Maximum number of packages to return (default: 10)

**Response (Raw Format):**
```json
{
  "packages": [
    {
      "package_id": 1,
      "package_name": "VIP Package",
      "event_id": 1,
      "event_title": "Spring Conference",
      "bookings": 35,
      "revenue": 17500.00
    }
  ],
  "total_packages": 25,
  "total_bookings": 450,
  "total_revenue": "125000.00"
}
```

**Response (ECharts Format):**
Returns a dual-axis chart with bars for booking count and line for revenue.

---

## Frontend Integration (Vue 3 + Nuxt 3)

### Install Dependencies

```bash
npm install echarts vue-echarts
```

### Example Component

```vue
<template>
  <div>
    <h2>Event Statistics Dashboard</h2>
    
    <!-- Revenue Overview -->
    <v-chart
      v-if="revenueData"
      :option="revenueData"
      style="height: 400px"
    />
    
    <!-- Status Distribution -->
    <v-chart
      v-if="statusData"
      :option="statusData"
      style="height: 400px"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, BarChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent
} from 'echarts/components'

// Register ECharts components
use([
  CanvasRenderer,
  PieChart,
  BarChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent
])

const revenueData = ref(null)
const statusData = ref(null)

onMounted(async () => {
  // Fetch revenue overview in ECharts format
  const revenueResponse = await fetch(
    '/api/v1/events/event/statistics/revenue-overview/?format=echarts',
    {
      headers: {
        'Authorization': `Bearer ${yourToken}`
      }
    }
  )
  revenueData.value = await revenueResponse.json()
  
  // Fetch status distribution in ECharts format
  const statusResponse = await fetch(
    '/api/v1/events/event/statistics/status-distribution/?format=echarts',
    {
      headers: {
        'Authorization': `Bearer ${yourToken}`
      }
    }
  )
  statusData.value = await statusResponse.json()
})
</script>
```

### Using TanStack Query (Recommended)

```typescript
// composables/useEventStatistics.ts
import { useQuery } from '@tanstack/vue-query'
import { useAuth } from './useAuth'

export const useEventStatistics = () => {
  const { token } = useAuth()
  
  const fetchStatistics = async (endpoint: string, params?: Record<string, any>) => {
    const queryString = new URLSearchParams({
      format: 'echarts',
      ...params
    }).toString()
    
    const response = await fetch(
      `/api/v1/events/event/statistics/${endpoint}/?${queryString}`,
      {
        headers: {
          'Authorization': `Bearer ${token.value}`
        }
      }
    )
    
    if (!response.ok) {
      throw new Error('Failed to fetch statistics')
    }
    
    return response.json()
  }
  
  const revenueOverview = useQuery({
    queryKey: ['event-statistics', 'revenue-overview'],
    queryFn: () => fetchStatistics('revenue-overview')
  })
  
  const statusDistribution = useQuery({
    queryKey: ['event-statistics', 'status-distribution'],
    queryFn: () => fetchStatistics('status-distribution')
  })
  
  const capacityUtilization = useQuery({
    queryKey: ['event-statistics', 'capacity-utilization'],
    queryFn: () => fetchStatistics('capacity-utilization')
  })
  
  return {
    revenueOverview,
    statusDistribution,
    capacityUtilization,
    fetchStatistics
  }
}
```

### Dashboard Component

```vue
<template>
  <div class="statistics-dashboard">
    <div class="metrics-grid">
      <MetricCard
        v-if="overview.data"
        title="Total Events"
        :value="overview.data.dashboard.metrics.total_events"
        icon="calendar"
      />
      <MetricCard
        v-if="overview.data"
        title="Total Revenue"
        :value="`$${overview.data.dashboard.metrics.total_revenue}`"
        icon="dollar"
      />
      <MetricCard
        v-if="overview.data"
        title="Total Bookings"
        :value="overview.data.dashboard.metrics.total_bookings"
        icon="ticket"
      />
    </div>
    
    <div class="charts-grid">
      <div class="chart-card">
        <h3>Revenue Overview</h3>
        <v-chart
          v-if="!revenue.isLoading && revenue.data"
          :option="revenue.data"
          style="height: 400px"
        />
        <p v-else-if="revenue.isLoading">Loading...</p>
        <p v-else-if="revenue.error">Error loading chart</p>
      </div>
      
      <div class="chart-card">
        <h3>Status Distribution</h3>
        <v-chart
          v-if="!status.isLoading && status.data"
          :option="status.data"
          style="height: 400px"
        />
      </div>
      
      <div class="chart-card">
        <h3>Capacity Utilization</h3>
        <v-chart
          v-if="!capacity.isLoading && capacity.data"
          :option="capacity.data"
          style="height: 400px"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useEventStatistics } from '~/composables/useEventStatistics'

const {
  revenueOverview: revenue,
  statusDistribution: status,
  capacityUtilization: capacity
} = useEventStatistics()
</script>

<style scoped>
.statistics-dashboard {
  padding: 2rem;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 1rem;
  margin-bottom: 2rem;
}

.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
  gap: 2rem;
}

.chart-card {
  background: white;
  border-radius: 8px;
  padding: 1.5rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}
</style>
```

## Error Handling

All endpoints return standard HTTP status codes:

- `200 OK`: Request successful
- `400 Bad Request`: Invalid parameters
- `401 Unauthorized`: Missing or invalid authentication
- `403 Forbidden`: Insufficient permissions
- `404 Not Found`: Resource not found
- `500 Internal Server Error`: Server error

Example error response:
```json
{
  "detail": "Invalid status parameter. Must be one of: DRAFTING, PUBLISHED, OPEN, IN_PROGRESS, COMPLETED, CLOSED, CANCELLED, POSTPONED"
}
```

## Rate Limiting

API requests are rate-limited to prevent abuse. Current limits:
- 100 requests per minute per user
- 1000 requests per hour per user

## Best Practices

1. **Use ECharts format for direct rendering**: When using vue-echarts, request `?format=echarts` to get ready-to-use configurations
2. **Cache responses**: Use TanStack Query or similar library to cache results and reduce API calls
3. **Filter strategically**: Apply filters at the API level rather than client-side for better performance
4. **Batch requests**: Use the overview endpoint for dashboard views instead of multiple individual requests
5. **Handle loading states**: Always show loading indicators while fetching data
6. **Error boundaries**: Implement error handling for failed requests

## OpenAPI Schema

Full OpenAPI v3 schema is available at:
```
/api/v1/schema/
```

Interactive API documentation:
```
/api/v1/docs/
```
