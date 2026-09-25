from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from configuration.translations import get_translation
from events.models import EventRegistration
from media_designer.data import badge_rows, certificate_rows
from media_designer.forms import MediaTemplateCreateForm, MediaTemplateForm
from media_designer.models import MediaTemplate
from media_designer.rendering import render_pdf, sheet_layout
from media_designer.schema import PAPER_MM, translated_field_labels
from tournaments.models import Tournament, TournamentRegistration


def _require_staff(request):
    if not request.user.is_staff:
        raise PermissionDenied


@login_required
def template_list(request):
    _require_staff(request)
    form = MediaTemplateCreateForm()
    return render(request, 'media_designer/list.html', {
        'form': form,
        'templates': MediaTemplate.objects.select_related('event').all(),
    })


@login_required
@require_POST
def template_create(request):
    _require_staff(request)
    form = MediaTemplateCreateForm(request.POST, request.FILES)
    if form.is_valid():
        template = form.save(commit=False)
        template.created_by = request.user
        template.save()
        return redirect('media_template_edit', pk=template.pk)
    return render(request, 'media_designer/list.html', {
        'form': form,
        'templates': MediaTemplate.objects.select_related('event').all(),
    }, status=400)


@login_required
def template_edit(request, pk):
    _require_staff(request)
    template = get_object_or_404(MediaTemplate, pk=pk)
    form = MediaTemplateForm(request.POST or None, request.FILES or None, instance=template)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('media_template_edit', pk=template.pk)
    return render(request, 'media_designer/edit.html', {
        'template': template,
        'form': form,
        'field_labels': translated_field_labels(),
        'paper_mm': PAPER_MM,
    })


@login_required
def template_export(request, pk):
    _require_staff(request)
    template = get_object_or_404(MediaTemplate.objects.select_related('event'), pk=pk)
    error = None
    recipients = []
    tournaments = []
    tournament = None
    capacity = None

    if template.kind == MediaTemplate.Kind.BADGE:
        recipients = list(
            EventRegistration.objects.filter(event=template.event)
            .exclude(payment_status=EventRegistration.PaymentStatus.CANCELLED)
            .select_related('user').prefetch_related('seats')
            .order_by('user__username')
        )
        capacity = sheet_layout(template.paper_size)[2]
    else:
        tournaments = list(Tournament.objects.filter(
            event=template.event, status=Tournament.Status.FINISHED,
        ).order_by('title'))
        tournament_id = request.POST.get('tournament') if request.method == 'POST' else request.GET.get('tournament')
        tournament = next((item for item in tournaments if str(item.pk) == str(tournament_id)), None)
        if not tournament and tournaments and request.method == 'GET':
            tournament = tournaments[0]
        if tournament:
            recipients = list(
                TournamentRegistration.objects.filter(tournament=tournament)
                .select_related('team').order_by('team__name')
            )

    if request.method == 'POST':
        selected = request.POST.getlist('recipients')
        valid_ids = {str(item.pk) for item in recipients}
        if not selected or len(selected) > 1000 or len(selected) != len(set(selected)) or not set(selected) <= valid_ids:
            error = get_translation('media_error_recipients', 'Bitte gültige Empfänger auswählen (höchstens 1.000 pro Export).')
        elif template.kind == MediaTemplate.Kind.CERTIFICATE and not tournament:
            error = get_translation('media_error_tournament', 'Bitte ein abgeschlossenes Turnier wählen.')
        else:
            selected_set = set(selected)
            chosen = [item for item in recipients if str(item.pk) in selected_set]
            if template.kind == MediaTemplate.Kind.BADGE:
                rows = badge_rows(chosen, template.event)
            else:
                award_title = request.POST.get('award_title', '').strip()[:120] or get_translation('media_award_default', 'Turnierurkunde')
                rows = certificate_rows([item.team for item in chosen], tournament, award_title)
            try:
                pdf = render_pdf(template, rows, on_a4=request.POST.get('sheet') == 'a4')
            except (ValueError, ValidationError) as exc:
                error = '; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            else:
                filename = f'{slugify(template.name) or "medienexport"}.pdf'
                return FileResponse(pdf, as_attachment=True, filename=filename, content_type='application/pdf')

    return render(request, 'media_designer/export.html', {
        'template': template,
        'recipients': recipients,
        'tournaments': tournaments,
        'tournament': tournament,
        'capacity': capacity,
        'error': error,
    }, status=400 if error else 200)
