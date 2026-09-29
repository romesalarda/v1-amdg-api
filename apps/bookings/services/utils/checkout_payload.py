"""
Checkout payload preparation helpers.

Builds the JSON-safe attendee payload persisted on Payment.metadata, and
materializes any multipart question-answer uploads into Resource records
before that payload is built.
"""
import json
import typing

from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder

from apps.common.models import Resource, ResourceTypeChoices
from apps.events.models import Event
from django.contrib.auth.models import User


class CheckoutPayloadBuilder:
    """Prepares checkout attendee selections for storage on Payment.metadata."""

    @staticmethod
    def serialize_attendees(
        selections: typing.List[typing.Dict[str, typing.Any]]
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """Serialize attendee selections into a JSON-safe metadata payload."""
        serialized = []
        for selection in selections:
            attendee = selection.get('_attendee')
            draft = selection.get('_attendee_draft') or {}
            package = selection['_package']

            product_rows = []
            for prod_selection in selection.get('product_selections', []):
                package_product = prod_selection['_package_product']
                variant = prod_selection['_variant']
                product_rows.append({
                    'package_product_id': package_product.id,
                    'variant_id': str(variant.variant_id),
                    'product_id': str(variant.product.product_id),
                    'quantity': int(prod_selection['quantity']),
                })

            question_answers = []
            for answer in draft.get('question_answers', []) or []:
                answer_row = {
                    'question_id': str(answer.get('question_id')) if answer.get('question_id') else None,
                    'answer_text': answer.get('answer_text'),
                    'selected_option_ids': answer.get('selected_option_ids') or [],
                    'upload_resource_id': answer.get('upload_resource_id'),
                    'upload_url': answer.get('upload_url'),
                }
                # Keep metadata payload JSON-safe and avoid persisting multipart mapping internals.
                question_answers.append(answer_row)

            draft_payload = {
                **draft,
                'question_answers': question_answers,
            }

            serialized.append({
                'attendee_id': str(attendee.attendee_id) if attendee else None,
                'attendee_draft': (
                    json.loads(json.dumps(draft_payload, cls=DjangoJSONEncoder))
                    if not attendee else None
                ),
                'package_id': package.id,
                'product_selections': product_rows,
            })
        return serialized

    @staticmethod
    def materialize_multipart_uploads(selections: list, event: Event, actor: User) -> None:
        """
        Materialize any multipart question uploads into Resource objects and attach
        their IDs and URLs to the attendee draft answers.

        Args:
            selections: List of attendee selections with potential multipart uploads.
            event: The event for which the booking is being made.
            actor: The user performing the checkout action.
        """
        content_type = ContentType.objects.get_for_model(event.__class__)

        for selection in selections:
            draft = selection.get('_attendee_draft') or {}
            answers = draft.get('question_answers', []) or []
            for answer in answers:
                upload_file = answer.pop('_upload_file', None)
                answer.pop('upload_file_key', None)
                if not upload_file:
                    continue

                content_type_value = str(getattr(upload_file, 'content_type', '') or '').lower()
                is_image = content_type_value.startswith('image/')

                resource_kwargs = {
                    'name': getattr(upload_file, 'name', 'question-upload'),
                    'resource_type': ResourceTypeChoices.IMAGE if is_image else ResourceTypeChoices.DOCUMENT,
                    'target_type': content_type,
                    'target_id': event.id,
                    'added_by': actor,
                    'public': False,
                    'tag': 'QUESTION_UPLOAD',
                }

                if is_image:
                    resource_kwargs['image'] = upload_file
                else:
                    resource_kwargs['file'] = upload_file

                resource = Resource.objects.create(**resource_kwargs)
                answer['upload_resource_id'] = resource.id
                answer['upload_url'] = resource.resource_url
                if not answer.get('answer_text'):
                    answer['answer_text'] = resource.resource_url or ''
