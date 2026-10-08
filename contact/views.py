from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from configuration.translations import get_translation as tr
from .forms import ContactForm
from .services import is_contact_available, submit_contact
from .tokens import make_submission_token

@never_cache
@require_http_methods(['GET', 'POST'])
def contact_form(request):
    if not is_contact_available():
        return render(request, 'contact/form.html', {'available': False})
    if request.method == 'POST':
        form = ContactForm(request.POST, request=request)
        if form.is_valid():
            try:
                submit_contact(
                    request, email=form.cleaned_data['email'],
                    category_id=form.cleaned_data['category'].pk,
                    message=form.cleaned_data['message'],
                    submission_token=form.cleaned_data['submission_token'],
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, tr('contact_success'))
                return redirect('contact:form')
    else:
        form = ContactForm(request=request, initial={
            'email': request.user.email if request.user.is_authenticated else '',
            'submission_token': make_submission_token(request),
        })
    return render(request, 'contact/form.html', {'available': True, 'form': form})
