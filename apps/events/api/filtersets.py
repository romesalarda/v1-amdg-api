from django_filters import rest_framework as filters
from django.db.models import Q
from apps.events.models import (
    Event, EventType, EventAuthorization, EventPermission,
    EventRole, EventStaff, EventReview, EventQuestion,
    EventQuestionAnswer
)


class EventTypeFilterSet(filters.FilterSet):
    title = filters.CharFilter(lookup_expr='icontains')
    code = filters.CharFilter(lookup_expr='icontains')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EventType
        fields = ['title', 'code', 'created_by']
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(title__icontains=value) |
            Q(code__icontains=value) |
            Q(description__icontains=value)
        )


class EventFilterSet(filters.FilterSet):
    title = filters.CharFilter(lookup_expr='icontains')
    status = filters.MultipleChoiceFilter(choices=Event._meta.get_field('status').choices)
    start_date_after = filters.DateFilter(field_name='start_datetime', lookup_expr='gte')
    start_date_before = filters.DateFilter(field_name='start_datetime', lookup_expr='lte')
    end_date_after = filters.DateFilter(field_name='end_datetime', lookup_expr='gte')
    end_date_before = filters.DateFilter(field_name='end_datetime', lookup_expr='lte')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = Event
        fields = ['status', 'event_type', 'organisation', 'created_by']
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(title__icontains=value) |
            Q(display_identifier__icontains=value) |
            Q(description__icontains=value) |
            Q(venue__icontains=value)
        )


class EventAuthorizationFilterSet(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=EventAuthorization._meta.get_field('status').choices)
    event_title = filters.CharFilter(field_name='event__title', lookup_expr='icontains')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EventAuthorization
        fields = ['event', 'status', 'reviewed_by']
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(event__title__icontains=value) |
            Q(notes__icontains=value)
        )


class EventPermissionFilterSet(filters.FilterSet):
    name = filters.CharFilter(lookup_expr='icontains')
    code = filters.CharFilter(lookup_expr='icontains')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EventPermission
        fields = ['name', 'code', 'category']
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(name__icontains=value) |
            Q(code__icontains=value) |
            Q(description__icontains=value)
        )


class EventRoleFilterSet(filters.FilterSet):
    name = filters.CharFilter(lookup_expr='icontains')
    code = filters.CharFilter(lookup_expr='icontains')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EventRole
        fields = ['name', 'code', 'category']
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(name__icontains=value) |
            Q(code__icontains=value) |
            Q(description__icontains=value)
        )


class EventStaffFilterSet(filters.FilterSet):
    user_email = filters.CharFilter(field_name='user__email', lookup_expr='icontains')
    user_name = filters.CharFilter(method='filter_user_name')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EventStaff
        fields = ['event', 'user']
    
    def filter_user_name(self, queryset, name, value):
        return queryset.filter(
            Q(user__first_name__icontains=value) |
            Q(user__last_name__icontains=value) |
            Q(user__email__icontains=value)
        )
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(user__first_name__icontains=value) |
            Q(user__last_name__icontains=value) |
            Q(user__email__icontains=value) |
            Q(notes__icontains=value)
        )


class EventReviewFilterSet(filters.FilterSet):
    rating_min = filters.NumberFilter(field_name='rating', lookup_expr='gte')
    rating_max = filters.NumberFilter(field_name='rating', lookup_expr='lte')
    event_title = filters.CharFilter(field_name='event__title', lookup_expr='icontains')
    user_email = filters.CharFilter(field_name='user__email', lookup_expr='icontains')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EventReview
        fields = ['event', 'user', 'approved', 'rating']
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(comment__icontains=value) |
            Q(event__title__icontains=value) |
            Q(user__email__icontains=value)
        )


class EventQuestionFilterSet(filters.FilterSet):
    question_title = filters.CharFilter(lookup_expr='icontains')
    question_body = filters.CharFilter(lookup_expr='icontains')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = EventQuestion
        fields = ['event', 'question_type', 'required', 'public']
    
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(question_title__icontains=value) |
            Q(question_body__icontains=value)
        )


class EventQuestionAnswerFilterSet(filters.FilterSet):
    """
    Filterset for EventQuestionAnswer with attendee UUID support.
    
    Supports filtering by:
    - Question ID
    - Attendee ID (integer primary key)
    - Attendee ID (UUID - public facing)
    - Event ID (through question)
    - Answer text search
    
    Example queries:
        ?question=123
        ?attendee=456
        ?attendee_id=550e8400-e29b-41d4-a716-446655440000
        ?event=789
        ?search=answer text
    """
    
    # Question filters
    question = filters.NumberFilter(
        field_name='question__id',
        help_text="Filter by question ID"
    )
    question__event = filters.NumberFilter(
        field_name='question__event__id',
        help_text="Filter by event ID (through question)"
    )
    
    # Attendee filters
    attendee = filters.NumberFilter(
        field_name='attendee__id',
        help_text="Filter by attendee ID (integer primary key)"
    )
    attendee_id = filters.UUIDFilter(
        field_name='attendee__attendee_id',
        help_text="Filter by attendee UUID (public facing identifier)"
    )
    attendee_email = filters.CharFilter(
        field_name='attendee__email',
        lookup_expr='icontains',
        help_text="Filter by attendee email"
    )
    
    # Event filter (shortcut through question)
    event = filters.NumberFilter(
        field_name='question__event__id',
        help_text="Filter by event ID"
    )
    event__event_id = filters.UUIDFilter(
        field_name='question__event__event_id',
        help_text="Filter by event UUID"
    )
    
    # Answer text search
    answer_text = filters.CharFilter(
        field_name='answer_text',
        lookup_expr='icontains',
        help_text="Search in answer text"
    )
    
    search = filters.CharFilter(
        method='filter_search',
        help_text="Search across answer text and question title"
    )
    
    class Meta:
        model = EventQuestionAnswer
        fields = [
            'question', 'question__event',
            'attendee', 'attendee_id', 'attendee_email',
            'event', 'event__event_id',
            'answer_text', 'search'
        ]
    
    def filter_search(self, queryset, name, value):
        """Full-text search across answer text and question title."""
        return queryset.filter(
            Q(answer_text__icontains=value) |
            Q(question__question_title__icontains=value)
        )
