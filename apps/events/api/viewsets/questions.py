from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes

from apps.events.models import (
    Event, 
    EventQuestion, EventQuestionOption,
    EventQuestionAnswer, EventQuestionAnswerChoice,
)
from apps.common.api.serializers import (
    ResourceSerializer
)
from apps.events.api.serializers import (
    EventQuestionSerializer, EventQuestionOptionSerializer,
    EventQuestionAnswerSerializer, EventQuestionAnswerChoiceSerializer,
)
from apps.events.api.filtersets import EventQuestionAnswerFilterSet,EventQuestionFilterSet
    

from apps.events.api.pagination import StandardPagination


@extend_schema_view(
    list=extend_schema(
        summary="List Event Questions",
        description=(
            "Retrieve a paginated list of event questions used for registration forms and surveys. "
            "Questions can be various types (text, multiple choice, rating, etc.) and are displayed to attendees during registration. "
            "Supports filtering by event, question type, required status, and public visibility. Ordered by question order."
        ),
        tags=["Event Questions"],
        parameters=[
            OpenApiParameter(name='event', type=OpenApiTypes.STR, description='Filter by event URL-safe title'),
            OpenApiParameter(name='question_type', type=OpenApiTypes.STR, description='Filter by question type'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Question Details",
        description=(
            "Retrieve detailed information about a specific event question including "
            "question text, type, options, validation rules, and display settings."
        ),
        tags=["Event Questions"],
    ),
    create=extend_schema(
        summary="Create Event Question",
        description=(
            "Create a new event question for registration forms or surveys. "
            "Specify question type, text, required status, and options if applicable. "
            "Only event managers and administrators can create questions."
        ),
        tags=["Event Questions"],
    ),
    update=extend_schema(
        summary="Update Event Question",
        description=(
            "Update an event question with complete payload including all options. "
            "Use PATCH for partial updates. Only event managers and administrators can update questions."
        ),
        tags=["Event Questions"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Question",
        description=(
            "Partially update an event question such as changing text or required status. "
            "Only event managers and administrators can update questions."
        ),
        tags=["Event Questions"],
    ),
    destroy=extend_schema(
        summary="Delete Event Question",
        description=(
            "Delete an event question. Use with caution as this removes all associated answers. "
            "Only event managers and administrators can delete questions."
        ),
        tags=["Event Questions"],
    )
)
class EventQuestionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event questions for registration forms and surveys.
    
    Provides CRUD operations for creating custom questions that attendees
    answer during registration. Supports various question types and validation.
    """
    queryset = EventQuestion.objects.select_related('event').prefetch_related('options').all()
    serializer_class = EventQuestionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = EventQuestionFilterSet
    ordering_fields = ['order', 'created_at']
    ordering = ['order']
    
    def perform_create(self, serializer):
        """Create question and broadcast to WebSocket clients."""
        from apps.events.utils.websocket import broadcast_question_event_sync
        from apps.events.api.serializers import EventQuestionSerializer
        import logging
        import json
        from django.core.serializers.json import DjangoJSONEncoder
        
        logger = logging.getLogger(__name__)
        
        # Save the question
        instance = serializer.save()
        
        # Get actor object (not just email)
        actor = None
        if self.request.user and self.request.user.is_authenticated:
            actor = {
                'id': self.request.user.id,
                'email': self.request.user.email,
                'name': getattr(self.request.user, 'get_full_name', lambda: None)() or self.request.user.email
            }
        
        logger.info(f"[EventQuestionViewSet] Created question {instance.id} by {actor.get('email') if actor else 'unknown'}")
        
        # Serialize for broadcast (refetch to include options)
        instance.refresh_from_db()
        broadcast_serializer = EventQuestionSerializer(instance)
        question_data = json.loads(json.dumps(broadcast_serializer.data, cls=DjangoJSONEncoder))
        
        # Broadcast to WebSocket clients
        broadcast_question_event_sync(
            event_id=str(instance.event.event_id),
            event_type="question.created",
            question_data=question_data,
            actor=actor
        )
        
        logger.info(f"[EventQuestionViewSet] Broadcasted question.created for {instance.id} with actor: {actor}")
        
    def perform_update(self, serializer):
        """Update question and broadcast to WebSocket clients."""
        from apps.events.utils.websocket import broadcast_question_event_sync
        from apps.events.api.serializers import EventQuestionSerializer
        import logging
        import json
        from django.core.serializers.json import DjangoJSONEncoder
        
        logger = logging.getLogger(__name__)
        
        # Save the question
        instance = serializer.save()
        
        # Get actor object (not just email)
        actor = None
        if self.request.user and self.request.user.is_authenticated:
            actor = {
                'id': self.request.user.id,
                'email': self.request.user.email,
                'name': getattr(self.request.user, 'get_full_name', lambda: None)() or self.request.user.email
            }
        
        logger.info(f"[EventQuestionViewSet] Updated question {instance.id} by {actor.get('email') if actor else 'unknown'}")
        
        # Serialize for broadcast (refetch to include options)
        instance.refresh_from_db()
        broadcast_serializer = EventQuestionSerializer(instance)
        question_data = json.loads(json.dumps(broadcast_serializer.data, cls=DjangoJSONEncoder))
        
        # Broadcast to WebSocket clients
        broadcast_question_event_sync(
            event_id=str(instance.event.event_id),
            event_type="question.updated",
            question_data=question_data,
            actor=actor
        )
        
        logger.info(f"[EventQuestionViewSet] Broadcasted question.updated for {instance.id} with actor: {actor}")
    
    def perform_destroy(self, instance):
        """Delete question and broadcast to WebSocket clients."""
        from apps.events.utils.websocket import broadcast_question_event_sync
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Get data before deletion
        event_id = str(instance.event.event_id)
        question_id = str(instance.id)
        
        # Get actor object (not just email)
        actor = None
        if self.request.user and self.request.user.is_authenticated:
            actor = {
                'id': self.request.user.id,
                'email': self.request.user.email,
                'name': getattr(self.request.user, 'get_full_name', lambda: None)() or self.request.user.email
            }
        
        logger.info(f"[EventQuestionViewSet] Deleting question {question_id} by {actor.get('email') if actor else 'unknown'}")
        
        # Delete the question
        instance.delete()
        
        # Broadcast deletion
        broadcast_question_event_sync(
            event_id=event_id,
            event_type="question.deleted",
            question_data={
                "id": question_id,
                "event": event_id,
            },
            actor=actor
        )        
        logger.info(f"[EventQuestionViewSet] Broadcasted question.deleted for {question_id} with actor: {actor}")
        
    @extend_schema(
        summary="Bulk Create Questions",
        description=(
            "Create multiple event questions in a single request with nested options. "
            "All questions are validated before any are created (all-or-nothing). "
            "Useful for importing pre-built forms or creating entire sections at once. "
            "\n\n**Features:**\n"
            "- Atomic transaction: all questions created or none\n"
            "- Supports nested options for choice questions\n"
            "- Validates all questions before creating any\n"
            "- Returns all created questions with IDs\n"
            "\n\n**Request Format:**\n"
            "Array of question objects, each with:\n"
            "- event: Event UUID\n"
            "- question_title: String\n"
            "- question_body: String\n"
            "- question_type: Choice type\n"
            "- required: Boolean (optional)\n"
            "- order: Integer (optional)\n"
            "- options: Array of {option_text, order} (for choice questions)\n"
        ),
        tags=["Event Questions"],
        request={
            'application/json': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'event': {'type': 'string', 'format': 'uuid'},
                        'question_title': {'type': 'string'},
                        'question_body': {'type': 'string'},
                        'question_type': {'type': 'string'},
                        'required': {'type': 'boolean'},
                        'order': {'type': 'integer'},
                        'options': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'option_text': {'type': 'string'},
                                    'order': {'type': 'integer'}
                                }
                            }
                        }
                    }
                }
            }
        },
        responses={
            201: EventQuestionSerializer(many=True),
            400: OpenApiResponse(description='Validation errors in one or more questions')
        }
    )
    @action(detail=False, methods=['post'], url_path='bulk-create')
    def bulk_create(self, request):
        """
        Bulk create multiple questions with nested options atomically.
        """
        from django.db import transaction
        
        if not isinstance(request.data, list):
            return Response(
                {'detail': 'Request data must be an array of questions'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate all questions first
        serializers_list = []
        for question_data in request.data:
            serializer = EventQuestionSerializer(data=question_data, context={'request': request})
            if not serializer.is_valid():
                return Response(
                    {
                        'detail': 'Validation failed',
                        'errors': serializer.errors
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            serializers_list.append(serializer)
        
        # All valid - create atomically
        created_questions = []
        with transaction.atomic():
            for serializer in serializers_list:
                question = serializer.save()
                created_questions.append(question)
        
        # Return all created questions
        output_serializer = EventQuestionSerializer(
            created_questions,
            many=True,
            context={'request': request}
        )
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        summary="Reorder Questions",
        description=(
            "Update the display order of multiple questions in a single atomic operation. "
            "Useful for drag-and-drop reordering in form builders. "
            "\n\n**Features:**\n"
            "- Atomic transaction: all orders updated or none\n"
            "- Validates all question IDs exist and belong to same event\n"
            "- Handles unique constraint by updating in correct sequence\n"
            "- Broadcasts update via WebSocket after success\n"
            "\n\n**Request Format:**\n"
            "```json\n"
            "{\n"
            '  "questions": [\n'
            '    {"id": "uuid1", "order": 0},\n'
            '    {"id": "uuid2", "order": 1},\n'
            '    {"id": "uuid3", "order": 2}\n'
            "  ]\n"
            "}\n"
            "```"
        ),
        tags=["Event Questions"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'questions': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'string', 'format': 'uuid'},
                                'order': {'type': 'integer'}
                            },
                            'required': ['id', 'order']
                        }
                    }
                },
                'required': ['questions']
            }
        },
        responses={
            200: OpenApiResponse(description='Questions reordered successfully'),
            400: OpenApiResponse(description='Validation errors')
        }
    )
    @action(detail=False, methods=['post'], url_path='reorder')
    def reorder(self, request):
        """
        Reorder questions atomically.
        """
        from django.db import transaction
        from apps.events.utils.websocket import broadcast_question_event_sync
        import uuid
        
        questions_data = request.data.get('questions', [])
        
        if not questions_data:
            return Response(
                {'detail': 'questions array is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Extract and validate question IDs
            question_ids = [item['id'] for item in questions_data]
            
            # Fetch all questions
            questions = EventQuestion.objects.filter(id__in=question_ids)
            
            if questions.count() != len(question_ids):
                return Response(
                    {'detail': 'One or more question IDs not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Verify all questions belong to the same event
            event_ids = questions.values_list('event_id', flat=True).distinct()
            if len(event_ids) > 1:
                return Response(
                    {'detail': 'All questions must belong to the same event'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get event for broadcasting
            event_id = str(event_ids[0]) if event_ids else None
            
            # Update orders atomically
            with transaction.atomic():
                # Create a mapping of ID to order
                order_map = {item['id']: item['order'] for item in questions_data}
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"[EventQuestionViewSet] Reordering questions for event {event_id} with order map: {order_map}")
                # Update each question's order
                for question in questions:
                    question.order = order_map[str(question.id)]
                    question.save(update_fields=['order'])
            
            # Broadcast reorder event to WebSocket clients
            if event_id:
                actor = None
                if request.user and request.user.is_authenticated:
                    actor = {
                        'id': request.user.id,
                        'email': request.user.email,
                        'name': request.user.get_full_name() or request.user.email,
                    }
                
                broadcast_question_event_sync(
                    event_id=event_id,
                    event_type='question.reordered',
                    question_data={'question_ids': question_ids},
                    actor=actor
                )
            
            return Response({'message': 'Questions reordered successfully'})
        
        except KeyError as e:
            return Response(
                {'detail': f'Missing required field: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'detail': f'Error reordering questions: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema_view(
    list=extend_schema(
        summary="List Event Question Options",
        description=(
            "Retrieve a paginated list of question options for multiple choice and dropdown questions. "
            "Options define the available choices attendees can select when answering questions. "
            "Supports filtering by question to view all options for a specific question."
        ),
        tags=["Event Question Options"],
        parameters=[
            OpenApiParameter(name='question', type=OpenApiTypes.UUID, description='Filter by question ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Question Option Details",
        description=(
            "Retrieve detailed information about a specific question option including "
            "option text, value, display order, and associated question."
        ),
        tags=["Event Question Options"],
    ),
    create=extend_schema(
        summary="Create Event Question Option",
        description=(
            "Create a new option for a multiple choice or dropdown question. "
            "Specify option text, value, and display order. "
            "Only event managers and administrators can create options."
        ),
        tags=["Event Question Options"],
    ),
    update=extend_schema(
        summary="Update Event Question Option",
        description=(
            "Update a question option with complete payload. "
            "Use PATCH for partial updates. Only event managers and administrators can update options."
        ),
        tags=["Event Question Options"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Question Option",
        description=(
            "Partially update a question option such as changing text or order. "
            "Only event managers and administrators can update options."
        ),
        tags=["Event Question Options"],
    ),
    destroy=extend_schema(
        summary="Delete Event Question Option",
        description=(
            "Delete a question option. Affects questions using this option. "
            "Only event managers and administrators can delete options."
        ),
        tags=["Event Question Options"],
    )
)
class EventQuestionOptionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event question options for multiple choice questions.
    
    Provides CRUD operations for creating and managing options that attendees
    can select when answering multiple choice or dropdown questions.
    """
    queryset = EventQuestionOption.objects.select_related('question').all()
    serializer_class = EventQuestionOptionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['question']


@extend_schema_view(
    list=extend_schema(
        summary="List Event Question Answers",
        description=(
            "Retrieve a paginated list of answers submitted by attendees for event questions. "
            "Answers can be text responses, numeric values, or multiple choice selections. "
            "Supports filtering by question and attendee to view specific responses."
        ),
        tags=["Event Question Answers"],
        parameters=[
            OpenApiParameter(name='question', type=OpenApiTypes.UUID, description='Filter by question ID'),
            OpenApiParameter(name='attendee', type=OpenApiTypes.INT, description='Filter by attendee ID'),
        ]
    ),
    retrieve=extend_schema(
        summary="Get Event Question Answer Details",
        description=(
            "Retrieve detailed information about a specific answer including "
            "answer text, numeric value, selected options, attendee details, and submission time."
        ),
        tags=["Event Question Answers"],
    ),
    create=extend_schema(
        summary="Submit Event Question Answer",
        description=(
            "Submit a new answer to an event question during registration or survey completion. "
            "Answer format depends on question type (text, number, multiple choice, etc.). "
            "Validates answer against question requirements and constraints."
        ),
        tags=["Event Question Answers"],
    ),
    update=extend_schema(
        summary="Update Event Question Answer",
        description=(
            "Update an existing answer with complete payload. "
            "Use PATCH for partial updates. Attendees can update their own answers."
        ),
        tags=["Event Question Answers"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Question Answer",
        description=(
            "Partially update an answer such as changing text or selection. "
            "Attendees can update their own answers."
        ),
        tags=["Event Question Answers"],
    ),
    destroy=extend_schema(
        summary="Delete Event Question Answer",
        description=(
            "Delete an answer. Use with caution as this removes attendee response data. "
            "Only attendees or administrators can delete answers."
        ),
        tags=["Event Question Answers"],
    )
)
class EventQuestionAnswerViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event question answers submitted by attendees.
    
    Handles answer submission, updates, and retrieval. Validates answers
    against question constraints and supports various answer types.
    """
    queryset = EventQuestionAnswer.objects.select_related(
        'question', 'attendee'
    ).prefetch_related('selected_options').all()
    serializer_class = EventQuestionAnswerSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = EventQuestionAnswerFilterSet

    @extend_schema(
        summary="Upload Event Question File",
        description=(
            "Upload a file or image to be used as an answer for upload-type event questions. "
            "This endpoint stores the upload as a generic Resource linked to the event and "
            "returns the resource reference for use in checkout payloads. "
            "Use the returned resource ID in checkout as upload_resource_id."
        ),
        tags=["Event Question Answers"],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'event_id': {
                        'type': 'string',
                        'format': 'uuid',
                        'description': 'Event UUID the upload belongs to'
                    },
                    'name': {
                        'type': 'string',
                        'description': 'Optional name for the resource (defaults to file name)'
                    },
                    'description': {
                        'type': 'string',
                        'description': 'Optional description for the upload'
                    },
                    'resource_type': {
                        'type': 'string',
                        'enum': ['DOCUMENT', 'IMAGE', 'OTHER'],
                        'description': 'Resource type (DOCUMENT for files, IMAGE for images)'
                    },
                    'file': {
                        'type': 'string',
                        'format': 'binary',
                        'description': 'File upload for DOCUMENT/OTHER types'
                    },
                    'image': {
                        'type': 'string',
                        'format': 'binary',
                        'description': 'Image upload for IMAGE type'
                    }
                },
                'required': ['event_id']
            }
        },
        responses={
            201: ResourceSerializer,
            400: OpenApiResponse(description='Validation errors'),
            403: OpenApiResponse(description='Permission denied')
        }
    )
    @action(
        detail=False,
        methods=['post'],
        url_path='upload',
        permission_classes=[permissions.IsAuthenticated],
        parser_classes=[MultiPartParser, FormParser]
    )
    def upload(self, request):
        event_id = request.data.get('event_id')
        if not event_id:
            return Response(
                {'detail': 'event_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        event = get_object_or_404(Event, event_id=event_id)

        resource_type = request.data.get('resource_type', 'DOCUMENT')
        resource_type = resource_type.upper()
        if resource_type not in ['DOCUMENT', 'IMAGE', 'OTHER']:
            return Response(
                {'detail': 'resource_type must be DOCUMENT, IMAGE, or OTHER'},
                status=status.HTTP_400_BAD_REQUEST
            )

        upload_file = request.FILES.get('file')
        upload_image = request.FILES.get('image')

        if resource_type == 'IMAGE' and not upload_image:
            return Response(
                {'detail': 'image file is required for IMAGE resource type'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if resource_type in ['DOCUMENT', 'OTHER'] and not upload_file:
            return Response(
                {'detail': 'file is required for DOCUMENT/OTHER resource types'},
                status=status.HTTP_400_BAD_REQUEST
            )

        name = request.data.get('name')
        if not name:
            name = upload_image.name if upload_image else upload_file.name

        serializer_data = {
            'name': name,
            'description': request.data.get('description', ''),
            'resource_type': resource_type,
            'public': False,
        }

        if upload_image:
            serializer_data['image'] = upload_image
        if upload_file:
            serializer_data['file'] = upload_file

        serializer = ResourceSerializer(data=serializer_data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        content_type = ContentType.objects.get_for_model(Event)
        resource = serializer.save(
            target_type=content_type,
            target_id=event.id,
            added_by=request.user,
            tag='QUESTION_UPLOAD'
        )

        return Response(
            ResourceSerializer(resource, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )
    
    @extend_schema(
        summary="Submit Form (Batch Answers)",
        description=(
            "Submit all answers for a registration form in a single atomic transaction. "
            "Validates that all required questions are answered and creates all answers atomically. "
            "\n\n**Features:**\n"
            "- Atomic transaction: all answers created or none\n"
            "- Validates all required questions are answered\n"
            "- Supports text answers and option selections\n"
            "- Bulk creates all answers and choices\n"
            "- Returns complete submission with any validation errors\n"
            "\n\n**Request Format:**\n"
            "```json\n"
            "{\n"
            '  "attendee": 123,\n'
            '  "answers": [\n'
            "    {\n"
            '      "question": "uuid1",\n'
            '      "answer_text": "My answer",\n'
            '      "selected_option_ids": []\n'
            "    },\n"
            "    {\n"
            '      "question": "uuid2",\n'
            '      "answer_text": "",\n'
            '      "selected_option_ids": [1, 2]\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n"
        ),
        tags=["Event Question Answers"],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'attendee': {'type': 'integer'},
                    'answers': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'question': {'type': 'string', 'format': 'uuid'},
                                'answer_text': {'type': 'string'},
                                'selected_option_ids': {
                                    'type': 'array',
                                    'items': {'type': 'integer'}
                                }
                            },
                            'required': ['question']
                        }
                    }
                },
                'required': ['attendee', 'answers']
            }
        },
        responses={
            201: EventQuestionAnswerSerializer(many=True),
            400: OpenApiResponse(description='Validation errors or missing required answers')
        }
    )
    @action(detail=False, methods=['post'], url_path='submit-form')
    def submit_form(self, request):
        """
        Submit all form answers in a single atomic transaction.
        """
        from django.db import transaction
        
        attendee_id = request.data.get('attendee')
        answers_data = request.data.get('answers', [])
        
        if not attendee_id:
            return Response(
                {'detail': 'attendee is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not answers_data:
            return Response(
                {'detail': 'answers array is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Get all question IDs from answers
            question_ids = [answer['question'] for answer in answers_data]
            
            # Fetch all questions
            questions = EventQuestion.objects.filter(id__in=question_ids).prefetch_related('options')
            questions_dict = {str(q.id): q for q in questions}
            
            # Check if all questions exist
            if len(questions_dict) != len(question_ids):
                missing = set(question_ids) - set(questions_dict.keys())
                return Response(
                    {'detail': f'Questions not found: {missing}'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Get event from first question (all should be same event)
            first_question = next(iter(questions_dict.values()))
            event = first_question.event
            
            # Get all required questions for this event
            all_event_questions = event.questions.all()
            required_question_ids = set(
                str(q.id) for q in all_event_questions if q.required
            )
            answered_question_ids = set(question_ids)
            
            # Check if all required questions are answered
            missing_required = required_question_ids - answered_question_ids
            if missing_required:
                return Response(
                    {
                        'detail': 'Missing required questions',
                        'missing_question_ids': list(missing_required)
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate all answers
            validated_answers = []
            for answer_data in answers_data:
                # Add attendee to each answer
                answer_data['attendee'] = attendee_id
                
                serializer = EventQuestionAnswerSerializer(
                    data=answer_data,
                    context={'request': request}
                )
                
                if not serializer.is_valid():
                    return Response(
                        {
                            'detail': 'Validation failed',
                            'errors': serializer.errors,
                            'question': answer_data.get('question')
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                validated_answers.append(serializer)
            
            # All valid - create atomically
            created_answers = []
            with transaction.atomic():
                for serializer in validated_answers:
                    answer = serializer.save()
                    created_answers.append(answer)
            
            # Return all created answers
            output_serializer = EventQuestionAnswerSerializer(
                created_answers,
                many=True,
                context={'request': request}
            )
            return Response(output_serializer.data, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            return Response(
                {'detail': f'Error submitting form: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema_view(
    list=extend_schema(
        summary="List Event Question Answer Choices",
        description=(
            "Retrieve a paginated list of answer choices representing specific option selections for multiple choice answers. "
            "Each choice links an answer to a specific option that was selected. "
            "Used for tracking individual selections in multi-select questions."
        ),
        tags=["Event Question Answer Choices"],
    ),
    retrieve=extend_schema(
        summary="Get Event Question Answer Choice Details",
        description=(
            "Retrieve detailed information about a specific answer choice including "
            "the answer, selected option, and related question context."
        ),
        tags=["Event Question Answer Choices"],
    ),
    create=extend_schema(
        summary="Create Event Question Answer Choice",
        description=(
            "Create a new answer choice linking an answer to a selected option. "
            "Used when attendees select options in multiple choice questions. "
            "Automatically validated against available options."
        ),
        tags=["Event Question Answer Choices"],
    ),
    update=extend_schema(
        summary="Update Event Question Answer Choice",
        description=(
            "Update an answer choice. Rarely used as choices are typically created or deleted. "
            "Use with caution as this affects attendee responses."
        ),
        tags=["Event Question Answer Choices"],
    ),
    partial_update=extend_schema(
        summary="Partially Update Event Question Answer Choice",
        description=(
            "Partially update an answer choice. "
            "Use with caution as this affects attendee responses."
        ),
        tags=["Event Question Answer Choices"],
    ),
    destroy=extend_schema(
        summary="Delete Event Question Answer Choice",
        description=(
            "Delete an answer choice, removing an option selection from an answer. "
            "Used when attendees change their multiple choice selections."
        ),
        tags=["Event Question Answer Choices"],
    )
)
class EventQuestionAnswerChoiceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing event question answer choices for multiple choice answers.
    
    Handles the individual option selections within multiple choice answers.
    Each choice represents one selected option in a multiple choice question.
    """
    queryset = EventQuestionAnswerChoice.objects.select_related('answer', 'option').all()
    serializer_class = EventQuestionAnswerChoiceSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['answer']