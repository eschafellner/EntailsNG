from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.utils.html import format_html, format_html_join
from django.utils.functional import lazy
from django.urls import path, reverse
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from configuration.translations import get_translation
from tournaments.exceptions import TournamentError
from tournaments.models import (
    Game, Team, TeamMember, Tournament, TournamentMatch, TournamentMatchParticipant, TournamentRegistration, SwissRound
)
from tournaments.services import TournamentBracketService, TournamentRestartService
from tournaments.forms import TournamentMatchAdminForm, TournamentRestartForm


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('name', 'mode', 'team_size', 'created_at')
    search_fields = ('name', 'mode')
    prepopulated_fields = {'slug': ('name',)}


class TournamentRegistrationInline(admin.TabularInline):
    model = TournamentRegistration
    extra = 0
    raw_id_fields = ('team',)

    def get_readonly_fields(self, request, obj=None):
        return ('team', 'seed', 'is_forfeited', 'group_name', 'score') if obj and obj.is_generated else ()

    def has_add_permission(self, request, obj=None):
        return not (obj and obj.is_generated) and super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not (obj and obj.is_generated) and super().has_delete_permission(request, obj)


class TournamentMatchParticipantInline(admin.TabularInline):
    model = TournamentMatchParticipant
    extra = 0
    raw_id_fields = ('team',)
    readonly_fields = ('team', 'rank', 'score', 'is_disqualified', 'notes')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class TournamentMatchInline(admin.TabularInline):
    model = TournamentMatch
    extra = 0
    can_delete = False
    fields = (
        'bracket_type', 'round_number', 'match_number', 'team1', 'team2',
        'score_team1', 'score_team2', 'winner', 'status'
    )
    readonly_fields = (
        'bracket_type', 'round_number', 'match_number', 'team1', 'team2',
        'score_team1', 'score_team2', 'winner', 'status'
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    change_form_template = 'admin/tournaments/tournament/change_form.html'
    list_display = (
        'title', 'event', 'game', 'mode', 'status',
        'registered_count', 'max_teams', 'is_generated', 'registration_start', 'registration_end', 'tournament_start'
    )
    list_filter = ('event', 'mode', 'status', 'is_generated')
    search_fields = ('title', 'description', 'game__name')
    prepopulated_fields = {'slug': ('title',)}
    raw_id_fields = ('tournament_admin', 'tournament_support')
    inlines = [TournamentRegistrationInline, TournamentMatchInline]
    actions = [
        'action_close_registration_and_generate_bracket',
        'action_generate_bracket_preview',
        'action_reset_bracket',
    ]

    def get_readonly_fields(self, request, obj=None):
        history = ('restarted_from', 'restart_source_title', 'restarted_by', 'restart_reason',
                   'restart_cancelled_source', 'restart_team_snapshot', 'restart_history', 'created_at')
        if obj and obj.is_generated:
            return ('mode', 'event', 'game', 'swiss_rounds', 'swiss_allow_draws', 'is_generated',
                    'play_third_place', 'group_qualifiers_per_group', 'standings_tiebreak') + history
        return history

    def has_restart_permission(self, request, obj):
        return (Tournament.can_view_drafts(request.user) and self.has_change_permission(request, obj)
                and self.has_add_permission(request) and request.user.has_perm('tournaments.add_tournamentregistration'))

    def get_urls(self):
        return [path('<int:object_id>/restart/', self.admin_site.admin_view(self.restart_view),
                     name='tournaments_tournament_restart')] + super().get_urls()

    def change_view(self, request, object_id, form_url='', extra_context=None):
        obj = self.get_object(request, object_id)
        context = dict(extra_context or {})
        context['can_restart'] = bool(obj and self.has_restart_permission(request, obj))
        return super().change_view(request, object_id, form_url, context)

    def restart_history(self, obj):
        if not obj.pk:
            return '—'
        return format_html_join(' ', '<p><a href="{}">{}</a> · {}</p>', (
            (reverse('admin:tournaments_tournament_change', args=[edition.pk]),
             edition.title, edition.get_status_display()) for edition in obj.restart_editions.all())) or '—'

    restart_history.short_description = lazy(get_translation, str)('restart_editions')

    def restart_view(self, request, object_id):
        if request.method not in ('GET', 'POST'):
            return HttpResponseNotAllowed(['GET', 'POST'])
        source = self.get_object(request, object_id)
        if source is None:
            raise Http404()
        if not self.has_restart_permission(request, source):
            raise PermissionDenied(get_translation('restart_permission'))
        preview = TournamentRestartService.preview(source.pk, actor=request.user)
        source = preview['source']
        suffix_length = len(get_translation('restart_default_title', title=''))
        initial = {'title': get_translation('restart_default_title', title=source.title[:max(0, 150-suffix_length)])[:150],
            'registration_start': source.registration_start, 'registration_end': source.registration_end,
            'tournament_start': source.tournament_start, 'copy_seeds': True,
            'registration_ids': [str(r['id']) for r in preview['registrations']], 'preview_token': preview['token']}
        form = TournamentRestartForm(request.POST if request.method == 'POST' else None,
            preview=preview, initial=initial)
        if request.method == 'POST' and form.is_valid():
            try:
                edition, created = TournamentRestartService.create(source.pk, actor=request.user, **form.cleaned_data)
            except (TournamentError, ValidationError) as error:
                form.add_error(None, '; '.join(error.messages) if isinstance(error, ValidationError) else str(error))
            else:
                if created:
                    self.log_addition(request, edition, get_translation('restart_log', title=source.title))
                    if edition.restart_cancelled_source:
                        self.log_change(request, source, get_translation('restart_cancel_log', title=edition.title))
                self.message_user(request, get_translation('restart_success', title=edition.title), messages.SUCCESS)
                return redirect('admin:tournaments_tournament_change', edition.pk)
        context = {**self.admin_site.each_context(request), 'opts': self.model._meta, 'original': source,
            'title': get_translation('restart_prepare'), 'form': form, 'preview': preview,
            'source_url': reverse('admin:tournaments_tournament_change', args=[source.pk])}
        return TemplateResponse(request, 'admin/tournaments/tournament/restart.html', context)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            reg_count=models.Count('registrations', distinct=True)
        )

    def registered_count(self, obj):
        return getattr(obj, 'reg_count', obj.registrations.count())
    registered_count.short_description = "Angemeldete Teams"
    registered_count.admin_order_field = 'reg_count'

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == 'mode':
            from configuration.translations import get_translation
            kwargs['choices'] = [
                (val, get_translation(key, default))
                for val, key, default in [
                    (Tournament.Mode.SINGLE_ELIMINATION, 'tournament_mode_single_elimination', 'Single Elimination (KO-System)'),
                    (Tournament.Mode.DOUBLE_ELIMINATION, 'tournament_mode_double_elimination', 'Double Elimination (Winner + Loser Bracket)'),
                    (Tournament.Mode.LEAGUE, 'tournament_mode_league', 'Liga (Jeder gegen Jeden)'),
                    (Tournament.Mode.GROUP_STAGE, 'tournament_mode_group_stage', 'Gruppenspiele mit anschließendem KO-System'),
                    (Tournament.Mode.FFA, 'tournament_mode_ffa', 'Alle in einem (Free-For-All / Deathmatch)'),
                    (Tournament.Mode.SWISS, 'tournament_mode_swiss', 'Schweizer System'),
                ]
            ]
        elif db_field.name == 'status':
            from configuration.translations import get_translation
            kwargs['choices'] = [
                (val, get_translation(key, default))
                for val, key, default in [
                    (Tournament.Status.DRAFT, 'tournament_status_draft', 'Entwurf'),
                    (Tournament.Status.REGISTRATION_OPEN, 'tournament_status_open', 'Anmeldung geöffnet'),
                    (Tournament.Status.REGISTRATION_CLOSED, 'tournament_status_closed', 'Anmeldung geschlossen'),
                    (Tournament.Status.IN_PROGRESS, 'tournament_status_running', 'Turnier läuft'),
                    (Tournament.Status.FINISHED, 'tournament_status_finished', 'Beendet'),
                    (Tournament.Status.CANCELLED, 'tournament_status_cancelled', 'Abgesagt'),
                ]
            ]
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    @admin.action(description="Turnierbaum generieren & Turnier starten")
    def action_close_registration_and_generate_bracket(self, request, queryset):
        for tournament in queryset:
            if tournament.mode == Tournament.Mode.SWISS:
                from django.urls import reverse
                self.message_user(request, format_html(
                    'Schweizer System: <a href="{}">Paarungen prüfen und Runde freigeben</a>.',
                    reverse('tournament_swiss_preview', args=[tournament.slug])), messages.INFO)
                continue
            try:
                TournamentBracketService.generate_bracket(tournament.id, actor=request.user)
                self.message_user(
                    request,
                    f"Turnier '{tournament.title}': Turnierbaum erfolgreich generiert! Das Turnier läuft jetzt.",
                    messages.SUCCESS
                )
            except TournamentError as e:
                self.message_user(
                    request,
                    f"Turnier '{tournament.title}': {e}",
                    messages.ERROR
                )

    @admin.action(description="Vorschau des Turnierbaums im Admin-Protokoll anzeigen")
    def action_generate_bracket_preview(self, request, queryset):
        for tournament in queryset:
            try:
                preview_data = TournamentBracketService.get_bracket_preview(tournament.id)
                self.message_user(
                    request,
                    f"Vorschau für '{tournament.title}': {preview_data}",
                    messages.INFO
                )
            except Exception as e:
                self.message_user(
                    request,
                    f"Fehler bei Vorschau für '{tournament.title}': {e}",
                    messages.ERROR
                )

    @admin.action(description="Turnierbaum zurücksetzen & Anmeldung wieder öffnen")
    def action_reset_bracket(self, request, queryset):
        for tournament in queryset:
            try:
                TournamentBracketService.reset_bracket(tournament.id, actor=request.user)
                self.message_user(
                    request,
                    f"Turnier '{tournament.title}': Turnierbaum erfolgreich zurückgesetzt und Anmeldung wieder geöffnet.",
                    messages.SUCCESS
                )
            except TournamentError as e:
                self.message_user(
                    request,
                    f"Turnier '{tournament.title}': {e}",
                    messages.ERROR
                )


class TeamMemberInline(admin.TabularInline):
    model = TeamMember
    extra = 0
    raw_id_fields = ('user',)

    def get_readonly_fields(self, request, obj=None):
        return ('user', 'role', 'status') if obj and obj.is_in_active_tournament() else ()

    def has_add_permission(self, request, obj=None):
        return not (obj and obj.is_in_active_tournament()) and super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not (obj and obj.is_in_active_tournament()) and super().has_delete_permission(request, obj)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'tag', 'event', 'captain', 'game', 'invite_code', 'is_archived', 'is_solo', 'created_at')
    list_filter = ('event', 'is_archived', 'game', 'is_solo')
    search_fields = ('name', 'tag', 'invite_code', 'captain__username')
    prepopulated_fields = {'slug': ('name',)}
    raw_id_fields = ('captain', 'event')
    inlines = [TeamMemberInline]
    actions = ['action_archive_teams', 'action_unarchive_teams', 'action_forfeit_and_disqualify']

    def get_readonly_fields(self, request, obj=None):
        return ('event', 'game', 'captain', 'is_archived', 'is_solo') if obj and obj.is_in_active_tournament() else ()

    @admin.action(description="Ausgewählte Teams archivieren")
    def action_archive_teams(self, request, queryset):
        archived_count = 0
        skipped_count = 0
        for team in queryset:
            if team.is_in_active_tournament():
                skipped_count += 1
            else:
                team.is_archived = True
                team.save(update_fields=['is_archived'])
                archived_count += 1

        if archived_count > 0:
            self.message_user(request, f"{archived_count} Team(s) erfolgreich archiviert.", messages.SUCCESS)
        if skipped_count > 0:
            self.message_user(
                request,
                f"{skipped_count} Team(s) konnten nicht archiviert werden, da sie sich in laufenden Turnieren befinden.",
                messages.WARNING
            )

    @admin.action(description="Ausgewählte Teams aus dem Archiv wiederherstellen")
    def action_unarchive_teams(self, request, queryset):
        count = queryset.update(is_archived=False)
        self.message_user(request, f"{count} Team(s) als aktiv markiert.", messages.SUCCESS)

    @admin.action(description="Ausgewählte Teams aus laufenden Turnieren zurückziehen (Walkover vergeben)")
    def action_forfeit_and_disqualify(self, request, queryset):
        from tournaments.services import forfeit_team_in_active_tournaments
        count = 0
        for team in queryset:
            if team.is_in_active_tournament():
                forfeit_team_in_active_tournaments(team, reason="Admin-Entscheidung / Disqualifikation")
                count += 1
        if count > 0:
            self.message_user(
                request,
                f"{count} Team(s) erfolgreich aus Turnieren zurückgezogen und Freilose an Gegner vergeben.",
                messages.SUCCESS
            )
        else:
            self.message_user(request, "Keines der ausgewählten Teams befindet sich in einem aktiven Turnier.", messages.INFO)

    def delete_model(self, request, obj):
        obj.delete(force=True)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            obj.delete(force=True)


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ('user', 'team', 'role', 'status', 'joined_at')
    list_filter = ('role', 'status')
    search_fields = ('user__username', 'team__name')
    raw_id_fields = ('user', 'team')

    def get_readonly_fields(self, request, obj=None):
        return ('user', 'team', 'role', 'status') if obj and obj.team.is_in_active_tournament() else ()

    def has_delete_permission(self, request, obj=None):
        return not (obj and obj.team.is_in_active_tournament()) and super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'team':
            active = TournamentRegistration.objects.filter(
                models.Q(tournament__is_generated=True) | models.Q(tournament__status=Tournament.Status.IN_PROGRESS)
            ).exclude(tournament__status__in=(Tournament.Status.FINISHED, Tournament.Status.CANCELLED))
            kwargs['queryset'] = Team.objects.exclude(pk__in=active.values('team_id'))
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(TournamentRegistration)
class TournamentRegistrationAdmin(admin.ModelAdmin):
    list_display = ('tournament', 'team', 'seed', 'group_name', 'score', 'registered_at')
    list_filter = ('tournament', 'group_name')
    search_fields = ('tournament__title', 'team__name')
    raw_id_fields = ('tournament', 'team')

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'tournament':
            kwargs['queryset'] = Tournament.objects.filter(is_generated=False).exclude(
                status__in=(Tournament.Status.IN_PROGRESS, Tournament.Status.FINISHED, Tournament.Status.CANCELLED))
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        return ('tournament', 'team', 'seed', 'is_forfeited', 'group_name', 'score') if obj and (obj.tournament.is_generated or obj.swiss_entries.exists()) else ()

    def has_delete_permission(self, request, obj=None):
        return not (obj and (obj.tournament.is_generated or obj.swiss_entries.exists())) and super().has_delete_permission(request, obj)


@admin.register(TournamentMatch)
class TournamentMatchAdmin(admin.ModelAdmin):
    form = TournamentMatchAdminForm
    list_display = (
        '__str__', 'tournament', 'bracket_type', 'round_number',
        'match_number', 'team1', 'team2', 'score_team1', 'score_team2', 'winner', 'status'
    )
    list_filter = ('tournament', 'bracket_type', 'status', 'round_number')
    search_fields = ('tournament__title', 'team1__name', 'team2__name')
    readonly_fields = (
        'tournament', 'bracket_type', 'round_number', 'match_number', 'group_name',
        'is_bye', 'loser', 'next_match_winner', 'next_match_loser',
        'next_match_winner_slot', 'next_match_loser_slot', 'status',
        'result_editor',
    )
    raw_id_fields = ('team1', 'team2', 'winner')
    inlines = [TournamentMatchParticipantInline]

    @admin.display(description='Turnieransicht')
    def result_editor(self, obj):
        return format_html('<a href="{}">{}</a>', reverse('tournament_detail', args=[obj.tournament.slug]),
                           get_translation('tournament_match_admin_open', 'Turnier öffnen und Ergebnisse eintragen'))

    def get_readonly_fields(self, request, obj=None):
        extra = ('team1', 'team2', 'swiss_round', 'result_type')
        if obj and obj.bracket_type == TournamentMatch.BracketType.FFA:
            extra += ('score_team1', 'score_team2', 'winner', 'decision_reason')
        if obj and obj.bracket_type == TournamentMatch.BracketType.SWISS:
            if (obj.result_type != TournamentMatch.ResultType.PLAYED
                or obj.tournament.status != Tournament.Status.IN_PROGRESS
                or obj.tournament.swiss_round_records.filter(number__gt=obj.round_number).exists()):
                extra += ('score_team1', 'score_team2', 'winner', 'decision_reason')
        return self.readonly_fields + extra

    def get_form(self, request, obj=None, **kwargs):
        base = super().get_form(request, obj, **kwargs)
        class ActorForm(base):
            actor = request.user
        return ActorForm

    def has_add_permission(self, request):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    def has_delete_permission(self, request, obj=None):
        return not (obj and obj.tournament.is_generated) and super().has_delete_permission(request, obj)

    def delete_queryset(self, request, queryset):
        if queryset.filter(bracket_type=TournamentMatch.BracketType.SWISS).exists():
            raise ValidationError('Veröffentlichte Schweizer Matches können nicht einzeln gelöscht werden.')
        super().delete_queryset(request, queryset)

    def save_model(self, request, obj, form, change):
        if change and obj.bracket_type != TournamentMatch.BracketType.FFA:
            original = TournamentMatch.objects.get(pk=obj.pk)
            fields = ('score_team1', 'score_team2', 'winner_id', 'decision_reason')
            if not any(getattr(original, field) != getattr(obj, field) for field in fields):
                return
            if obj.score_team1 is None or obj.score_team2 is None:
                raise ValidationError(get_translation('audit_score_required', 'Bitte beide Ergebnisse angeben. Gewertete Ergebnisse dürfen nicht gelöscht werden.'))
        if change and obj.bracket_type != TournamentMatch.BracketType.FFA:
            if obj.score_team1 is not None and obj.score_team2 is not None:
                from tournaments.services.matches import TournamentMatchService
                from tournaments.exceptions import TournamentError
                orig = TournamentMatch.objects.get(pk=obj.pk)
                selected_winner = form.cleaned_data.get('winner')
                selected_winner_id = selected_winner.id if selected_winner else None
                if (
                    orig.status != TournamentMatch.Status.COMPLETED
                    or orig.score_team1 != obj.score_team1
                    or orig.score_team2 != obj.score_team2
                    or orig.winner_id != selected_winner_id
                    or orig.decision_reason != obj.decision_reason
                ):
                    try:
                        match, _ = TournamentMatchService.update_match_score(
                            match_id=obj.id,
                            score1=obj.score_team1,
                            score2=obj.score_team2,
                            winner_id=selected_winner_id,
                            decision_reason=obj.decision_reason,
                            actor=request.user,
                        )
                        obj.status = match.status
                        obj.winner = match.winner
                        obj.loser = match.loser
                        return
                    except TournamentError as e:
                        raise ValidationError(str(e))
        super().save_model(request, obj, form, change)


@admin.register(TournamentMatchParticipant)
class TournamentMatchParticipantAdmin(admin.ModelAdmin):
    list_display = ('match', 'team', 'rank', 'score', 'is_disqualified', 'created_at')
    list_filter = ('is_disqualified', 'rank')
    search_fields = ('team__name', 'match__tournament__title')
    raw_id_fields = ('match', 'team')
    readonly_fields = ('match', 'team', 'rank', 'score', 'is_disqualified', 'notes')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SwissRound)
class SwissRoundAdmin(admin.ModelAdmin):
    list_display = ('tournament', 'number', 'published_at', 'published_by', 'repeat_pairings_approved')
    list_filter = ('tournament',)
    readonly_fields = ('tournament', 'number', 'published_at', 'published_by', 'input_digest', 'standings_snapshot', 'repeat_pairings_approved')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
