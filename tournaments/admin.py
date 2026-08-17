from django.contrib import admin, messages
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
    raw_id_fields = ('team1', 'team2', 'winner', 'loser', 'next_match_winner', 'next_match_loser')


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'event', 'game', 'mode', 'status',
        'registered_count', 'max_teams', 'is_generated', 'registration_start', 'registration_end'
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

    def registered_count(self, obj):
        return obj.registrations.count()
    registered_count.short_description = "Angemeldete Teams"

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
    actions = ['action_archive_teams', 'action_unarchive_teams']

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
    raw_id_fields = ('tournament', 'team1', 'team2', 'winner', 'loser', 'next_match_winner', 'next_match_loser')
    inlines = [TournamentMatchParticipantInline]


@admin.register(TournamentMatchParticipant)
class TournamentMatchParticipantAdmin(admin.ModelAdmin):
    list_display = ('match', 'team', 'rank', 'score', 'is_disqualified', 'created_at')
    list_filter = ('is_disqualified', 'rank')
    search_fields = ('team__name', 'match__tournament__title')
    raw_id_fields = ('match', 'team')
