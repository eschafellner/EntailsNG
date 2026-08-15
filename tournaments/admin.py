from django.contrib import admin, messages
from django.utils.html import format_html
from tournaments.models import (
    Game, Team, TeamMember, Tournament, TournamentMatch, TournamentRegistration
)
from tournaments.services import generate_bracket


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('name', 'mode', 'team_size', 'created_at')
    search_fields = ('name', 'mode')
    prepopulated_fields = {'slug': ('name',)}


class TournamentRegistrationInline(admin.TabularInline):
    model = TournamentRegistration
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
    actions = ['action_close_registration_and_generate_bracket', 'action_generate_bracket_preview']

    def registered_count(self, obj):
        return obj.registrations.count()
    registered_count.short_description = "Angemeldete Teams"

    @admin.action(description="Anmeldung schließen & Turnierbaum generieren")
    def action_close_registration_and_generate_bracket(self, request, queryset):
        for tournament in queryset:
            tournament.status = Tournament.Status.REGISTRATION_CLOSED
            tournament.save()
            res = generate_bracket(tournament, preview=False)
            if res:
                self.message_user(
                    request,
                    f"Turnier '{tournament.title}': Anmeldung geschlossen und Turnierbaum erfolgreich generiert!",
                    messages.SUCCESS
                )
            else:
                self.message_user(
                    request,
                    f"Turnier '{tournament.title}': Mindestens 2 angemeldete Teams erforderlich.",
                    messages.WARNING
                )

    @admin.action(description="Vorschau des Turnierbaums im Admin-Protokoll anzeigen")
    def action_generate_bracket_preview(self, request, queryset):
        for tournament in queryset:
            preview_data = generate_bracket(tournament, preview=True)
            self.message_user(
                request,
                f"Vorschau für '{tournament.title}': {preview_data}",
                messages.INFO
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
        count = queryset.update(is_archived=True)
        self.message_user(request, f"{count} Team(s) erfolgreich archiviert.", messages.SUCCESS)

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
