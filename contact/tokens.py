import uuid

from django.core import signing
from django.core.exceptions import ValidationError

from configuration.translations import get_translation as tr

TOKEN_SALT = 'contact.submission.v1'
TOKEN_MAX_AGE = 3600


def make_submission_token(request):
    scope = request.session.get('contact_form_scope')
    if not scope:
        scope = uuid.uuid4().hex
        request.session['contact_form_scope'] = scope
    return signing.dumps({
        'id': str(uuid.uuid4()), 'scope': scope,
        'user': request.user.pk if request.user.is_authenticated else None,
    }, salt=TOKEN_SALT)


def read_submission_token(request, token):
    try:
        data = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
        actor_id = request.user.pk if request.user.is_authenticated else None
        if data['scope'] != request.session.get('contact_form_scope') or data['user'] != actor_id:
            raise signing.BadSignature()
        return uuid.UUID(data['id'])
    except (signing.BadSignature, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValidationError(tr('contact_invalid_token'), code='invalid_token') from exc
