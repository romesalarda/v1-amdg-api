"""
ViewSets for the Event Forms system.

Provides CRUD operations and custom actions for EventForm, EventFormQuestion,
EventFormQuestionOption, EventFormResponse, EventFormResponseAnswer,
and EventFormDelegateToken.

Broadcasting pattern mirrors apps/events/api/viewsets/questions.py.
"""
import json
import logging
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from django.db import transaction
from django.db.models import Count, Q
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.request import Request

from django_filters.rest_framework import DjangoFilterBackend

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes

from apps.events.models import (
    EventForm, EventFormStatusChoices,
    EventFormQuestion, EventFormQuestionOption,
    EventFormResponse, EventFormResponseAnswer, EventFormResponseAnswerChoice,
    EventFormDelegateToken,
    EventRoleAssignment, EventRoleCategoryChoices,
)
from apps.events.api.permissions import IsEventStaffOrReadOnly, IsEventOwnerOrStaffMember
from apps.events.api.serializers import (
    EventFormSerializer, EventFormListSerializer,
    EventFormQuestionSerializer, EventFormQuestionOptionSerializer,
    EventFormResponseSerializer, EventFormResponseAnswerSerializer,
    EventFormDelegateTokenSerializer, EventFormDelegateTokenValidateSerializer,
)

from apps.events.api.serializers.form_response_filter import FormResponseFilterRequestSerializer

from apps.events.api.filtersets import (
    EventFormFilterSet, EventFormQuestionFilterSet,
    EventFormResponseFilterSet, EventFormResponseAnswerFilterSet,
)
from apps.events.api.pagination import StandardPagination
from apps.events.services.notifications import create_notification, NotificationTypeChoices, NotificationPriorityChoices
from apps.events.services.form_response_filters import FormResponseFilterService

logger = logging.getLogger(__name__)


def _get_actor(request: Request) -> dict | None:
    """
    Get actor information from the request user for broadcasting events.
    """
    if request.user and request.user.is_authenticated:
        return {
            'id': request.user.id,
            'email': request.user.email,
            'name': getattr(request.user, 'get_full_name', lambda: request.user.email)() or request.user.email,
        }
    return None


def _broadcast_form_event(event_id: str, event_type: str, data: dict, actor: dict | None = None):
    """
    Broadcast a form mutation event to the event_{event_id}_forms channel group.
    Args:
        event_id (str): The ID of the event.
        event_type (str): The type of the event (e.g., 'form.created').
        data (dict): The payload data to broadcast.
        actor (dict, optional): Information about the actor performing the action.
    """

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    group_name = f"event_{event_id}_forms"
    message = {
        "type": "form_event",
        "data": {
            "type": event_type,
            "payload": data,
            "timestamp": timezone.now().isoformat(),
            "actor": actor,
        },
    }
    try:
        async_to_sync(channel_layer.group_send)(group_name, message)
        logger.debug(f"[forms] Broadcast {event_type} to {group_name}")
    except Exception as exc:
        logger.error(f"[forms] Failed to broadcast {event_type} to {group_name}: {exc}", exc_info=True)


def _broadcast_form_response_event(event_id: str, event_type: str, data: dict, actor: dict | None = None):
    """
    Broadcast a response submission event to the event_{event_id}_form_responses channel group.
    Args:
        event_id (str): The ID of the event.
        event_type (str): The type of the event (e.g., 'response.created').
        data (dict): The payload data to broadcast.
        actor (dict, optional): Information about the actor performing the action.
    
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    group_name = f"event_{event_id}_form_responses"
    message = {
        "type": "form_response_event",
        "data": {
            "type": event_type,
            "payload": data,
            "timestamp": timezone.now().isoformat(),
            "actor": actor,
        },
    }
    try:
        async_to_sync(channel_layer.group_send)(group_name, message)
        logger.debug(f"[forms] Broadcast {event_type} to {group_name}")
    except Exception as exc:
        logger.error(f"[forms] Failed to broadcast {event_type} to {group_name}: {exc}", exc_info=True)


# ── EventFormViewSet ──────────────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary="List Event Forms", tags=["Event Forms"]),
    retrieve=extend_schema(summary="Get Event Form Details", tags=["Event Forms"]),
    create=extend_schema(summary="Create Event Form", tags=["Event Forms"]),
    update=extend_schema(summary="Update Event Form", tags=["Event Forms"]),
    partial_update=extend_schema(summary="Partially Update Event Form", tags=["Event Forms"]),
    destroy=extend_schema(summary="Delete Event Form", tags=["Event Forms"]),
)
class EventFormViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event forms.

    Supports CRUD plus lifecycle actions (publish/close) and bulk question creation.
    Broadcasts mutations to the event_{event_id}_forms WebSocket group.
    """
    permission_classes = [permissions.IsAuthenticated, IsEventStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    filterset_class = EventFormFilterSet
    ordering_fields = ['created_at', 'updated_at', 'title']
    ordering = ['-created_at']
    search_fields = ['title', 'description']

    def get_queryset(self):
        return (
            EventForm.objects.select_related('event', 'created_by')
            .prefetch_related('questions__options')
            .annotate(question_count=Count('questions'))
            .all()
        )

    def get_serializer_class(self):
        if self.action == 'list':
            return EventFormListSerializer
        return EventFormSerializer

    def _get_broadcast_data(self, instance):
        serializer = EventFormSerializer(instance, context={'request': self.request})
        return json.loads(json.dumps(serializer.data, cls=DjangoJSONEncoder))

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        instance.refresh_from_db()
        _broadcast_form_event(
            event_id=str(instance.event.event_id),
            event_type='form.created',
            data=self._get_broadcast_data(instance),
            actor=_get_actor(self.request),
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        instance.refresh_from_db()
        _broadcast_form_event(
            event_id=str(instance.event.event_id),
            event_type='form.updated',
            data=self._get_broadcast_data(instance),
            actor=_get_actor(self.request),
        )

    def perform_destroy(self, instance):
        event_id = str(instance.event.event_id)
        form_id = str(instance.id)
        instance.delete()
        _broadcast_form_event(
            event_id=event_id,
            event_type='form.deleted',
            data={'id': form_id},
            actor=_get_actor(self.request),
        )

    @extend_schema(
        summary="Publish Form",
        description="Transition the form from DRAFT to PUBLISHED.",
        tags=["Event Forms"],
        responses={200: EventFormSerializer},
    )
    @action(detail=True, methods=['post'], url_path='publish')
    def publish(self, request, pk=None):
        form = self.get_object()
        if form.status == EventFormStatusChoices.CLOSED:
            return Response(
                {'detail': 'Cannot publish a closed form.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        form.publish()
        form.refresh_from_db()
        _broadcast_form_event(
            event_id=str(form.event.event_id),
            event_type='form.published',
            data=self._get_broadcast_data(form),
            actor=_get_actor(request),
        )

        create_notification(
            event=form.event,
            message=f"{request.user} has just published the form '{form.title}'.",
            notification_type=NotificationTypeChoices.GENERAL,
            priority=NotificationPriorityChoices.NORMAL,
        )
        serializer = EventFormSerializer(form, context={'request': request})
        return Response(serializer.data)

    @extend_schema(
        summary="Close Form",
        description="Transition the form to CLOSED, preventing further responses.",
        tags=["Event Forms"],
        responses={200: EventFormSerializer},
    )
    @action(detail=True, methods=['post'], url_path='close')
    def close(self, request, pk=None):
        form = self.get_object()
        form.close()
        form.refresh_from_db()
        _broadcast_form_event(
            event_id=str(form.event.event_id),
            event_type='form.closed',
            data=self._get_broadcast_data(form),
            actor=_get_actor(request),
        )
        create_notification(
            event=form.event,
            message=f"{request.user} has just closed the form '{form.title}'.",
            notification_type=NotificationTypeChoices.GENERAL,
            priority=NotificationPriorityChoices.NORMAL,
        )
        serializer = EventFormSerializer(form, context={'request': request})
        return Response(serializer.data)

    @extend_schema(
        summary="Bulk Create Questions",
        description=(
            "Create multiple questions for this form in a single atomic request. "
            "All questions are validated before any are created."
        ),
        tags=["Event Forms"],
        responses={201: EventFormQuestionSerializer(many=True)},
    )
    @action(detail=True, methods=['post'], url_path='bulk-create-questions')
    def bulk_create_questions(self, request, pk=None):
        form = self.get_object()
        if not isinstance(request.data, list):
            return Response(
                {'detail': 'Request data must be an array of questions.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializers_list = []
        for q_data in request.data:
            q_data = dict(q_data)
            q_data['form'] = str(form.id)
            ser = EventFormQuestionSerializer(data=q_data, context={'request': request})
            if not ser.is_valid():
                return Response({'detail': 'Validation failed', 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)
            serializers_list.append(ser)

        created = []
        with transaction.atomic():
            for ser in serializers_list:
                created.append(ser.save())

        actor = _get_actor(request)
        _broadcast_form_event(
            event_id=str(form.event.event_id),
            event_type='form.questions_bulk_created',
            data={'form_id': str(form.id), 'question_count': len(created)},
            actor=actor,
        )
        output = EventFormQuestionSerializer(created, many=True, context={'request': request})
        return Response(output.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Reorder Questions",
        description=(
            "Update display order of multiple questions atomically. "
            "Request: `{\"questions\": [{\"id\": \"uuid\", \"order\": 0}, ...]}`"
        ),
        tags=["Event Forms"],
        responses={200: OpenApiResponse(description='Questions reordered successfully')},
    )
    @action(detail=True, methods=['post'], url_path='reorder-questions')
    def reorder_questions(self, request, pk=None):
        form = self.get_object()
        questions_data = request.data.get('questions', [])
        if not questions_data:
            return Response({'detail': 'questions array is required.'}, status=status.HTTP_400_BAD_REQUEST)

        question_ids = [item['id'] for item in questions_data]
        questions = EventFormQuestion.objects.filter(id__in=question_ids, form=form)
        if questions.count() != len(question_ids):
            return Response({'detail': 'One or more question IDs not found on this form.'}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            order_map = {str(item['id']): item['order'] for item in questions_data}
            for q in questions:
                if str(q.id) not in order_map:
                    continue  # shouldn't happen given the count check above, but skip safely
                q.order = order_map[str(q.id)]
                q.save(update_fields=['order'])

        try:
            question_ids = [item['id'] for item in questions_data]
            order_map = {str(item['id']): item['order'] for item in questions_data}
        except (KeyError, TypeError):
            return Response({'detail': 'Each item must include id and order.'}, status=status.HTTP_400_BAD_REQUEST)

        _broadcast_form_event(
            event_id=str(form.event.event_id),
            event_type='form.questions_reordered',
            data={'form_id': str(form.id), 'question_ids': question_ids},
            actor=_get_actor(request),
        )
        return Response({'message': 'Questions reordered successfully.'})


# ── EventFormQuestionViewSet ──────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary="List Form Questions", tags=["Event Form Questions"]),
    retrieve=extend_schema(summary="Get Form Question Details", tags=["Event Form Questions"]),
    create=extend_schema(summary="Create Form Question", tags=["Event Form Questions"]),
    update=extend_schema(summary="Update Form Question", tags=["Event Form Questions"]),
    partial_update=extend_schema(summary="Partially Update Form Question", tags=["Event Form Questions"]),
    destroy=extend_schema(summary="Delete Form Question", tags=["Event Form Questions"]),
)
class EventFormQuestionViewSet(viewsets.ModelViewSet):
    """ViewSet for managing individual form questions."""
    serializer_class = EventFormQuestionSerializer
    permission_classes = [permissions.IsAuthenticated, IsEventStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = EventFormQuestionFilterSet
    ordering_fields = ['order', 'created_at']
    ordering = ['order']

    def get_queryset(self):
        return EventFormQuestion.objects.select_related('form__event').prefetch_related('options').all()

    def _broadcast(self, instance, event_type):
        data = json.loads(json.dumps(
            EventFormQuestionSerializer(instance, context={'request': self.request}).data,
            cls=DjangoJSONEncoder,
        ))
        _broadcast_form_event(
            event_id=str(instance.form.event.event_id),
            event_type=event_type,
            data=data,
            actor=_get_actor(self.request),
        )

    def perform_create(self, serializer):
        instance = serializer.save()
        instance.refresh_from_db()
        self._broadcast(instance, 'question.created')

    def perform_update(self, serializer):
        instance = serializer.save()
        instance.refresh_from_db()
        self._broadcast(instance, 'question.updated')

    def perform_destroy(self, instance):
        event_id = str(instance.form.event.event_id)
        data = {'id': str(instance.id), 'form_id': str(instance.form_id)}
        instance.delete()
        _broadcast_form_event(event_id=event_id, event_type='question.deleted', data=data, actor=_get_actor(self.request))


# ── EventFormQuestionOptionViewSet ────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary="List Form Question Options", tags=["Event Form Question Options"]),
    retrieve=extend_schema(summary="Get Option Details", tags=["Event Form Question Options"]),
    create=extend_schema(summary="Create Option", tags=["Event Form Question Options"]),
    update=extend_schema(summary="Update Option", tags=["Event Form Question Options"]),
    partial_update=extend_schema(summary="Partially Update Option", tags=["Event Form Question Options"]),
    destroy=extend_schema(summary="Delete Option", tags=["Event Form Question Options"]),
)
class EventFormQuestionOptionViewSet(viewsets.ModelViewSet):
    """ViewSet for managing question options."""
    serializer_class = EventFormQuestionOptionSerializer
    permission_classes = [permissions.IsAuthenticated, IsEventStaffOrReadOnly]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ['order', 'created_at']
    ordering = ['order']

    def get_queryset(self):
        qs = EventFormQuestionOption.objects.select_related('question__form__event').all()
        question_id = self.request.query_params.get('question')
        if question_id:
            qs = qs.filter(question__id=question_id)
        return qs


# ── EventFormResponseViewSet ──────────────────────────────────────────────────
from rest_framework.exceptions import PermissionDenied


@extend_schema_view(
    list=extend_schema(
        summary="List Form Responses",
        description=(
            "Staff see all responses for forms they manage. "
            "Attendees see only their own responses."
        ),
        tags=["Event Form Responses"],
    ),
    retrieve=extend_schema(summary="Get Form Response Details", tags=["Event Form Responses"]),
    create=extend_schema(summary="Submit Form Response", tags=["Event Form Responses"]),
    update=extend_schema(summary="Update Form Response", tags=["Event Form Responses"]),
    partial_update=extend_schema(summary="Partially Update Form Response", tags=["Event Form Responses"]),
    destroy=extend_schema(summary="Delete Form Response", tags=["Event Form Responses"]),
)
class EventFormResponseViewSet(viewsets.ModelViewSet):
    """
    ViewSet for form responses.

    Attendees see and manage their own responses only.
    Event staff/owners can view all responses for their event forms.
    """
    serializer_class = EventFormResponseSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = EventFormResponseFilterSet
    ordering_fields = ['submitted_at', 'updated_at']
    ordering = ['-submitted_at']

    @extend_schema(
        summary='Advanced filter form responses',
        description=(
            'POST-based filter endpoint for EventFormResponse. '
            'Supports filtering by attendee demographics, attendee status, '
            'and per-question answer conditions for the specified form. '
            'Returns the same paginated format as the GET list endpoint.'
        ),
        tags=['Event Form Responses'],
        request=FormResponseFilterRequestSerializer,
        responses={
            200: OpenApiResponse(description='Paginated list of matching form responses'),
            400: OpenApiResponse(description='Validation error'),
        },
    )
    @action(detail=False, methods=['post'], url_path='filter')
    def filter_responses(self, request):
        """POST-based form response filter with demographic and question-answer conditions."""
        serializer = FormResponseFilterRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = FormResponseFilterService(request, serializer.validated_data)
        qs = service.get_queryset()
        items, meta = service.paginate(qs)

        result_serializer = EventFormResponseSerializer(
            items, many=True, context={'request': request}
        )
        return Response({
            **meta,
            'results': result_serializer.data,
        })

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return EventFormResponse.objects.none()
        qs = EventFormResponse.objects.select_related(
            'form__event', 'attendee'
        ).prefetch_related('answers__question', 'answers__selected_options__option').all()

        user = self.request.user
        # if user.is_staff or user.is_superuser:
        #     return qs

        # Event owners, assigned event staff, and ADMINISTRATIVE role holders see
        # every response for their event(s); everyone else only sees their own.
        administrative_event_ids = EventRoleAssignment.objects.filter(
            user=user, role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
        ).values_list('event_id', flat=True)
        managed_q = (
            Q(form__event__created_by=user)
            | Q(form__event__staff_members__user=user)
            | Q(form__event_id__in=administrative_event_ids)
        )
        own_q = Q(attendee__booking__made_by=user)

        return qs.filter(managed_q | own_q).distinct()

    def validate_form_is_open(self, form):
        if form.status != EventFormStatusChoices.PUBLISHED:
            raise PermissionDenied("This form is not currently accepting responses.")

    def validate_editing_allowed(self, form):
        if form.status == EventFormStatusChoices.CLOSED:
            raise PermissionDenied("This form is closed and responses can no longer be edited.")
        if not form.allow_response_editing:
            raise PermissionDenied("Response editing is not allowed for this form.")

    def perform_create(self, serializer):
        form = serializer.validated_data.get('form')
        self.validate_form_is_open(form)
        instance = serializer.save()
        instance.refresh_from_db()
        data = json.loads(json.dumps(
            EventFormResponseSerializer(instance, context={'request': self.request}).data,
            cls=DjangoJSONEncoder,
        ))
        _broadcast_form_response_event(
            event_id=str(instance.form.event.event_id),
            event_type='response.created',
            data=data,
            actor=_get_actor(self.request),
        )

    def perform_update(self, serializer):
        old_instance = serializer.instance
        
        self.validate_editing_allowed(old_instance.form)
        instance = serializer.save()
        instance.refresh_from_db()

        if old_instance.submitted_at != instance.submitted_at:
            create_notification(
                event=instance.form.event,
                message=f"{self.request.user} has just updated their response to the form '{instance.form.title}'.",
                notification_type=NotificationTypeChoices.GENERAL,
                priority=NotificationPriorityChoices.NORMAL,
            )

        data = json.loads(json.dumps(
            EventFormResponseSerializer(instance, context={'request': self.request}).data,
            cls=DjangoJSONEncoder,
        ))
        _broadcast_form_response_event(
            event_id=str(instance.form.event.event_id),
            event_type='response.updated',
            data=data,
            actor=_get_actor(self.request),
        )


# ── EventFormResponseAnswerViewSet ────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary="List Response Answers", tags=["Event Form Response Answers"]),
    retrieve=extend_schema(summary="Get Answer Details", tags=["Event Form Response Answers"]),
    create=extend_schema(summary="Submit Answer", tags=["Event Form Response Answers"]),
    update=extend_schema(summary="Update Answer", tags=["Event Form Response Answers"]),
    partial_update=extend_schema(summary="Partially Update Answer", tags=["Event Form Response Answers"]),
    destroy=extend_schema(summary="Delete Answer", tags=["Event Form Response Answers"]),
)
class EventFormResponseAnswerViewSet(viewsets.ModelViewSet):
    """
    ViewSet for individual question answers within a form response.
    Supports multipart/form-data for file upload answers.
    """
    serializer_class = EventFormResponseAnswerSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = EventFormResponseAnswerFilterSet
    ordering_fields = ['submitted_at']
    ordering = ['-submitted_at']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return EventFormResponseAnswer.objects.none()
        qs = EventFormResponseAnswer.objects.select_related(
            'response__form__event', 'response__attendee', 'question'
        ).prefetch_related('selected_options__option').all()

        user = self.request.user
        if user.is_staff or user.is_superuser:
            return qs

        administrative_event_ids = EventRoleAssignment.objects.filter(
            user=user, role__category=EventRoleCategoryChoices.ADMINISTRATIVE,
        ).values_list('event_id', flat=True)
        managed_q = (
            Q(response__form__event__created_by=user)
            | Q(response__form__event__staff_members__user=user)
            | Q(response__form__event_id__in=administrative_event_ids)
        )
        own_q = Q(response__attendee__booking__made_by=user)

        return qs.filter(managed_q | own_q).distinct()

    def perform_update(self, serializer):
        instance = serializer.instance
        form = instance.response.form
        if form.status == EventFormStatusChoices.CLOSED:
            raise PermissionDenied("This form is closed.")
        if not form.allow_response_editing:
            raise PermissionDenied("Response editing is not allowed for this form.")    
        serializer.save()


# ── EventFormDelegateTokenViewSet ─────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary="List Delegate Tokens", tags=["Event Form Delegate Tokens"]),
    retrieve=extend_schema(summary="Get Delegate Token Details", tags=["Event Form Delegate Tokens"]),
    create=extend_schema(summary="Create Delegate Token", tags=["Event Form Delegate Tokens"]),
    destroy=extend_schema(summary="Revoke Delegate Token", tags=["Event Form Delegate Tokens"]),
)
class EventFormDelegateTokenViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing delegate tokens.

    Allows a booking person or event staff to create a shareable token that
    delegates form-filling to an individual attendee.

    Public endpoint: GET /api/event/form-delegate-tokens/validate/?token=<uuid>
    """
    serializer_class = EventFormDelegateTokenSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return EventFormDelegateToken.objects.none()
        qs = EventFormDelegateToken.objects.select_related(
            'response__form__event', 'response__attendee', 'created_by'
        ).all()
        user = self.request.user
        if not (user.is_staff or user.is_superuser):
            qs = qs.filter(created_by=user)
        return qs

    @extend_schema(
        summary="Validate Delegate Token",
        description=(
            "Public endpoint. Provide `?token=<uuid>` to check if a delegate token is valid "
            "and retrieve the associated form and attendee details."
        ),
        tags=["Event Form Delegate Tokens"],
        parameters=[
            OpenApiParameter(name='token', type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY, required=True),
        ],
        responses={
            200: EventFormDelegateTokenValidateSerializer,
            400: OpenApiResponse(description='token query parameter required'),
            404: OpenApiResponse(description='Token not found or expired'),
        },
        auth=[],
    )
    @action(
        detail=False,
        methods=['get'],
        url_path='validate',
        permission_classes=[permissions.AllowAny],
    )
    def validate_token(self, request):
        token_value = request.query_params.get('token')
        if not token_value:
            return Response({'detail': 'token query parameter is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            token_obj = EventFormDelegateToken.objects.select_related(
                'response__form', 'response__attendee'
            ).get(token=token_value)
        except EventFormDelegateToken.DoesNotExist:
            return Response({'detail': 'Token not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not token_obj.is_valid:
            return Response({'detail': 'Token has expired or already been used.'}, status=status.HTTP_404_NOT_FOUND)

        response = token_obj.response
        data = {
            'token': token_obj.token,
            'is_valid': True,
            'form_id': response.form_id,
            'form_title': response.form.title,
            'attendee_id': str(getattr(response.attendee, 'attendee_id', response.attendee_id)),
            'expires_at': token_obj.expires_at,
        }
        serializer = EventFormDelegateTokenValidateSerializer(data)
        return Response(serializer.data)


__all__ = [
    'EventFormViewSet',
    'EventFormQuestionViewSet',
    'EventFormQuestionOptionViewSet',
    'EventFormResponseViewSet',
    'EventFormResponseAnswerViewSet',
    'EventFormDelegateTokenViewSet',
]
