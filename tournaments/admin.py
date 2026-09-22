from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.html import format_html
from tournaments.exceptions import TournamentError
from tournaments.models import (
    Game, Team, TeamMember, Tournament, TournamentMatch, TournamentMatchParticipant, TournamentRegistration
)
from tournaments.services import TournamentBracketService


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('name', 'mode', 'team_size', 'created_at')
    search_fields = ('name', 'mode')
    prepopulated_fields = {'slug': ('name',)}


class TournamentRegistrationInline(admin.TabularInline):
    model = TournamentRegistration
    extra = 0
    raw_id_fields = ('team',)


class TournamentMatchParticipantInline(admin.TabularInline):
    model = TournamentMatchParticipant
    extra = 0
    raw_id_fields = ('team',)


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


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'tag', 'event', 'captain', 'game', 'invite_code', 'is_archived', 'is_solo', 'created_at')
    list_filter = ('event', 'is_archived', 'game', 'is_solo')
    search_fields = ('name', 'tag', 'invite_code', 'captain__username')
    prepopulated_fields = {'slug': ('name',)}
    raw_id_fields = ('captain', 'event')
    inlines = [TeamMemberInline]
    actions = ['action_archive_teams', 'action_unarchive_teams', 'action_forfeit_and_disqualify']

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


@admin.register(TournamentRegistration)
class TournamentRegistrationAdmin(admin.ModelAdmin):
    list_display = ('tournament', 'team', 'seed', 'group_name', 'score', 'registered_at')
    list_filter = ('tournament', 'group_name')
    search_fields = ('tournament__title', 'team__name')
    raw_id_fields = ('tournament', 'team')


@admin.register(TournamentMatch)
class TournamentMatchAdmin(admin.ModelAdmin):
    list_display = (
        '__str__', 'tournament', 'bracket_type', 'round_number',
        'match_number', 'team1', 'team2', 'score_team1', 'score_team2', 'winner', 'status'
    )
    list_filter = ('tournament', 'bracket_type', 'status', 'round_number')
    search_fields = ('tournament__title', 'team1__name', 'team2__name')
    readonly_fields = (
        'tournament', 'bracket_type', 'round_number', 'match_number',
        'is_bye', 'loser', 'next_match_winner', 'next_match_loser',
        'next_match_winner_slot', 'next_match_loser_slot', 'status',
    )
    raw_id_fields = ('team1', 'team2', 'winner')
    inlines = [TournamentMatchParticipantInline]

    def save_model(self, request, obj, form, change):
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
