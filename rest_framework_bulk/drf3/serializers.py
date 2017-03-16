from __future__ import print_function, unicode_literals

from rest_framework.exceptions import ValidationError
from rest_framework.serializers import ListSerializer, empty

from rest_framework.settings import api_settings
from rest_framework.utils import html

__all__ = [
    'BulkListSerializer',
    'BulkSerializerMixin',
]


class BulkSerializerMixin(object):
    def to_internal_value(self, data):
        ret = super(BulkSerializerMixin, self).to_internal_value(data)

        id_attr = getattr(self.Meta, 'update_lookup_field', 'id')
        request_method = getattr(getattr(self.context.get('view'), 'request'), 'method', '')

        # add update_lookup_field field back to validated data
        # since super by default strips out read-only fields
        # hence id will no longer be present in validated_data
        if all((isinstance(self.root, BulkListSerializer),
                id_attr,
                request_method in ('PUT', 'PATCH'))):
            id_field = self.fields[id_attr]
            id_value = id_field.get_value(data)

            ret[id_attr] = id_value

        return ret


class BulkListSerializer(ListSerializer):
    update_lookup_field = 'id'

    def to_internal_value(self, data):
        """
        List of dicts of native values <- List of dicts of primitive datatypes.
        """
        # These validations are copy-paste from DRF as there's no way to call them separately
        if html.is_html_input(data):
            data = html.parse_html_list(data)

        if not isinstance(data, list):
            message = self.error_messages['not_a_list'].format(
                input_type=type(data).__name__
            )
            raise ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: [message]
            }, code='not_a_list')

        if not self.allow_empty and len(data) == 0:
            message = self.error_messages['empty']
            raise ValidationError({
                api_settings.NON_FIELD_ERRORS_KEY: [message]
            }, code='empty')

        # We need additional preparations to correctly validate bulk update
        is_update = self.instance is not None
        if is_update:
            id_attr = getattr(self.child.Meta, 'update_lookup_field', 'id')
            data_by_id = {i.get(id_attr): i for i in data}
            if not all([None if id_ is empty else id_ for id_ in data_by_id.keys()]):
                raise ValidationError('All objects to update must have `id`')

            instances = self.instance.filter(**{
                id_attr + '__in': data_by_id.keys(),
            })
            self.instances_by_id = {obj.pk: obj for obj in instances}

            if len(data_by_id) != len(self.instances_by_id):
                raise ValidationError('Could not find all objects to update.')

        ret = []
        errors = []
        for item in data:
            try:
                if is_update:
                    # Set instance temporarily into the child during validation process
                    id_ = item[id_attr]
                    self.child.instance = self.instances_by_id[id_]

                validated = self.child.run_validation(item)
            except ValidationError as exc:
                errors.append(exc.detail)
            else:
                ret.append(validated)
                errors.append({})

        # Return original instance we had previously before the validation
        self.child.instance = self.instance

        if any(errors):
            raise ValidationError(errors)

        return ret

    def update(self, queryset, all_validated_data):
        id_attr = getattr(self.child.Meta, 'update_lookup_field', 'id')
        all_validated_data_by_id = {
            i.pop(id_attr): i
            for i in all_validated_data
        }

        updated_objects = []
        for id_, obj in self.instances_by_id.items():
            obj_validated_data = all_validated_data_by_id.get(id_)

            # use model serializer to actually update the model
            # in case that method is overwritten
            updated_objects.append(
                self.child.update(obj, obj_validated_data)
            )

        return updated_objects
