import uuid
import secrets
from django.conf import settings
from django.db import models
from django.utils.text import slugify
from django.utils import timezone


class Game(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Spielname")
    slug = models.SlugField(max_length=100, unique=True, blank=True, verbose_name="URL-Slug")
    mode = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Spielmodus",
        help_text="z. B. 5v5 Bomb Scenario, 1v1 Aim Map, Deathmatch",
    )
    team_size = models.PositiveIntegerField(
        default=5,
        verbose_name="Teamgröße",
        help_text="Anzahl der Spieler pro Team (1 = Einzelspieler / Solo)",
    )
    logo = models.ImageField(
        upload_to="game_logos/",
        blank=True,
        null=True,
        verbose_name="Spiellogo",
    )
    rules = models.TextField(blank=True, verbose_name="Regeln & Einstellungen")
    additional_info = models.TextField(blank=True, verbose_name="Zusätzliche Informationen")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Erstellt am")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Zuletzt geändert")

    class Meta:
        verbose_name = "Spiel"
        verbose_name_plural = "Spiele"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.team_size}v{self.team_size})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or "game"
            slug = base_slug
            count = 1
            while Game.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{count}"
                count += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Tournament(models.Model):
    class Mode(models.TextChoices):
        SINGLE_ELIMINATION = 'SINGLE_ELIMINATION', 'Single Elimination (KO-System)'
        DOUBLE_ELIMINATION = 'DOUBLE_ELIMINATION', 'Double Elimination (Winner + Loser Bracket)'
        LEAGUE = 'LEAGUE', 'Liga (Jeder gegen Jeden)'
        GROUP_STAGE = 'GROUP_STAGE', 'Gruppenspiele mit anschließendem KO-System'
        FFA = 'FFA', 'Alle in einem (Free-For-All / Deathmatch)'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Entwurf'
        REGISTRATION_OPEN = 'OPEN', 'Anmeldung geöffnet'
        REGISTRATION_CLOSED = 'CLOSED', 'Anmeldung geschlossen'
        IN_PROGRESS = 'IN_PROGRESS', 'Turnier läuft'
        FINISHED = 'FINISHED', 'Beendet'
        CANCELLED = 'CANCELLED', 'Abgesagt'

    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='tournaments',
        verbose_name="Veranstaltung",
    )
    game = models.ForeignKey(
        Game,
        on_delete=models.PROTECT,
        related_name='tournaments',
        verbose_name="Spiel",
    )
    title = models.CharField(max_length=150, verbose_name="Turniertitel")
    slug = models.SlugField(max_length=150, unique=True, blank=True, verbose_name="URL-Slug")
    description = models.TextField(blank=True, verbose_name="Beschreibung / Preise")

    mode = models.CharField(
        max_length=30,
        choices=Mode.choices,
        default=Mode.SINGLE_ELIMINATION,
        verbose_name="Turniermodus",
    )

    max_teams = models.PositiveIntegerField(
        default=16,
        verbose_name="Max. Teams / Teilnehmer",
    )

    registration_start = models.DateTimeField(verbose_name="Anmeldebeginn")
    registration_end = models.DateTimeField(verbose_name="Anmeldeschluss")

    tournament_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='managed_tournaments',
        verbose_name="Turnieradmin",
    )
    tournament_support = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='supported_tournaments',
        verbose_name="Turniersupport",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="Status",
    )

    is_generated = models.BooleanField(
        default=False,
        verbose_name="Turnierbaum generiert",
        help_text="Zeigt an, ob der Turnierbaum für dieses Turnier offiziell generiert wurde.",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Erstellt am")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Zuletzt geändert")

    class Meta:
        verbose_name = "Turnier"
        verbose_name_plural = "Turniere"
        ordering = ["-registration_start", "title"]

    def __str__(self):
        return f"{self.title} ({self.get_mode_display()})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title) or "turnier"
            slug = base_slug
            count = 1
            while Tournament.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{count}"
                count += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def is_registration_open(self):
        now = timezone.now()
        return (
            self.status == self.Status.REGISTRATION_OPEN
            and (self.registration_start is None or self.registration_start <= now)
            and (self.registration_end is None or now <= self.registration_end)
        )

    def can_register(self, user=None, team=None):
        """
        Zentrale Validierung, ob ein Team oder Spieler für dieses Turnier angemeldet werden darf.
        Rückgabe: Tuple (can_register: bool, reason: str)
        """
        now = timezone.now()

        if self.status != self.Status.REGISTRATION_OPEN:
            return False, f"Die Anmeldung für '{self.title}' ist aktuell nicht geöffnet (Status: {self.get_status_display()})."

        if self.registration_start and now < self.registration_start:
            formatted_start = self.registration_start.strftime('%d.%m.%Y %H:%M')
            return False, f"Die Anmeldung für '{self.title}' beginnt erst am {formatted_start} Uhr."

        if self.registration_end and now > self.registration_end:
            formatted_end = self.registration_end.strftime('%d.%m.%Y %H:%M')
            return False, f"Der Anmeldeschluss für '{self.title}' war am {formatted_end} Uhr."

        if self.is_generated or self.status in [self.Status.IN_PROGRESS, self.Status.FINISHED]:
            return False, f"Das Turnier '{self.title}' läuft bereits oder ist beendet."

        if self.max_teams and self.registrations.count() >= self.max_teams:
            return False, f"Die maximale Teilnehmeranzahl ({self.max_teams}) für '{self.title}' ist bereits erreicht."

        if team and self.registrations.filter(team=team).exists():
            return False, f"Das Team '{team.name}' ist bereits für dieses Turnier angemeldet."

        return True, ""

    def registered_teams_count(self):
        return self.registrations.count()


def generate_invite_code():
    return secrets.token_hex(4).upper()


class Team(models.Model):
    name = models.CharField(max_length=100, verbose_name="Teamname")
    slug = models.SlugField(max_length=100, unique=True, blank=True, verbose_name="URL-Slug")
    tag = models.CharField(max_length=10, blank=True, verbose_name="Clan-/Team-Tag")
    game = models.ForeignKey(
        Game,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="teams",
        verbose_name="Spiel",
    )
    captain = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="captain_teams",
        verbose_name="Kapitän",
    )
    invite_code = models.CharField(
        max_length=12,
        default=generate_invite_code,
        unique=True,
        verbose_name="Einladungscode",
        help_text="Code für direkten Beitritt weiterer Teammitglieder",
    )
    is_solo = models.BooleanField(
        default=False,
        verbose_name="Einzelspieler-Team",
        help_text="Automatisch erstelltes Solo-Team für 1v1 Turniere",
    )
    event = models.ForeignKey(
        'events.Event',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="teams",
        verbose_name="Veranstaltung",
        help_text="Die Veranstaltung, für die dieses Team aktuell antritt.",
    )
    is_archived = models.BooleanField(
        default=False,
        verbose_name="Archiviert",
        help_text="Zeigt an, ob das Team aus einer früheren Veranstaltung archiviert wurde.",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Erstellt am")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Zuletzt geändert")


    class Meta:
        verbose_name = "Team"
        verbose_name_plural = "Teams"
        ordering = ["name"]

    def __str__(self):
        if self.tag:
            return f"[{self.tag}] {self.name}"
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or "team"
            slug = base_slug
            count = 1
            while Team.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{count}"
                count += 1
            self.slug = slug
        if not self.invite_code:
            self.invite_code = generate_invite_code()
        super().save(*args, **kwargs)

    def get_accepted_members(self):
        return self.memberships.filter(status=TeamMember.Status.ACCEPTED).select_related('user')

    def get_pending_members(self):
        return self.memberships.filter(status=TeamMember.Status.PENDING).select_related('user')

    def is_member(self, user):
        if not user or not user.is_authenticated:
            return False
        return self.memberships.filter(user=user, status=TeamMember.Status.ACCEPTED).exists()

    def is_captain(self, user):
        if not user or not user.is_authenticated:
            return False
        return self.captain_id == user.id

    def is_in_active_tournament(self):
        """
        Prüft, ob das Team in einem generierten oder laufenden Turnier registriert ist.
        """
        return self.tournament_registrations.filter(
            models.Q(tournament__is_generated=True) |
            models.Q(tournament__status=Tournament.Status.IN_PROGRESS)
        ).exists()

    def delete(self, *args, **kwargs):
        force = kwargs.pop('force', False)
        if not force and self.is_in_active_tournament():
            from django.core.exceptions import ValidationError
            raise ValidationError(
                f"Das Team '{self.name}' kann nicht gelöscht werden, da es in einem laufenden oder generierten Turnier registriert ist."
            )
        super().delete(*args, **kwargs)

    def leave_team(self, user):
        """
        Entfernt einen User aus dem Team.
        Wenn der Kapitän austritt, geht die Kapitänswürde an ein beliebiges anderes aktives Mitglied.
        Verlässt das letzte Mitglied das Team, wird das Team gelöscht (außer bei aktivem Turnier).
        """
        membership = self.memberships.filter(user=user).first()
        if not membership:
            return False

        if self.is_in_active_tournament():
            accepted_count = self.memberships.filter(status=TeamMember.Status.ACCEPTED).count()
            if accepted_count <= 1:
                return 'in_active_tournament'

        membership.delete()

        remaining_memberships = self.memberships.filter(status=TeamMember.Status.ACCEPTED).order_by('joined_at')
        if not remaining_memberships.exists():
            self.delete()
            return 'deleted'

        if self.captain_id == user.id:
            new_captain = remaining_memberships.first()
            self.captain = new_captain.user
            self.save(update_fields=['captain'])
            new_captain.role = TeamMember.Role.CAPTAIN
            new_captain.save(update_fields=['role'])
            return 'captain_transferred'

        return 'left'


class TeamMember(models.Model):
    class Role(models.TextChoices):
        CAPTAIN = 'CAPTAIN', 'Kapitän'
        MEMBER = 'MEMBER', 'Mitglied'

    class Status(models.TextChoices):
        ACCEPTED = 'ACCEPTED', 'Mitglied'
        PENDING = 'PENDING', 'Anfrage ausstehend'

    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name="Team",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tournament_memberships',
        verbose_name="Benutzer",
    )
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.MEMBER,
        verbose_name="Rolle",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACCEPTED,
        verbose_name="Status",
    )
    joined_at = models.DateTimeField(auto_now_add=True, verbose_name="Beigetreten am")

    class Meta:
        verbose_name = "Team-Mitgliedschaft"
        verbose_name_plural = "Team-Mitgliedschaften"
        unique_together = ('team', 'user')
        ordering = ['role', 'joined_at']

    def __str__(self):
        return f"{self.user.username} @ {self.team.name} ({self.get_role_display()})"


class TournamentRegistration(models.Model):
    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name='registrations',
        verbose_name="Turnier",
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name='tournament_registrations',
        verbose_name="Team",
    )
    registered_at = models.DateTimeField(auto_now_add=True, verbose_name="Angemeldet am")
    seed = models.PositiveIntegerField(null=True, blank=True, verbose_name="Seed / Platzierung")
    group_name = models.CharField(max_length=20, blank=True, verbose_name="Gruppe (z.B. Gruppe A)")
    score = models.IntegerField(default=0, verbose_name="Punkte / Kills (für FFA)")

    class Meta:
        verbose_name = "Turnieranmeldung"
        verbose_name_plural = "Turnieranmeldungen"
        unique_together = ('tournament', 'team')
        ordering = ['registered_at']

    def __str__(self):
        return f"{self.team.name} -> {self.tournament.title}"


class TournamentMatch(models.Model):
    class BracketType(models.TextChoices):
        WINNERS = 'WINNERS', 'Winner Bracket'
        LOSERS = 'LOSERS', 'Loser Bracket'
        GRAND_FINAL = 'GRAND_FINAL', 'Grand Final'
        GRAND_FINAL_RESET = 'GRAND_FINAL_RESET', 'Grand Final Reset'
        FINAL = 'FINAL', 'Finale'
        GROUP = 'GROUP', 'Gruppenspiel'
        FFA = 'FFA', 'Free For All'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Ausstehend'
        READY = 'READY', 'Bereit'
        IN_PROGRESS = 'IN_PROGRESS', 'Läuft'
        COMPLETED = 'COMPLETED', 'Beendet'

    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name='matches',
        verbose_name="Turnier",
    )
    round_number = models.PositiveIntegerField(default=1, verbose_name="Runde")
    match_number = models.PositiveIntegerField(default=1, verbose_name="Match-Nummer in Runde")
    bracket_type = models.CharField(
        max_length=20,
        choices=BracketType.choices,
        default=BracketType.WINNERS,
        verbose_name="Bracket Typ",
    )

    group_name = models.CharField(max_length=20, blank=True, verbose_name="Gruppe (für Gruppenspiele)")

    team1 = models.ForeignKey(
        Team,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='matches_as_team1',
        verbose_name="Team 1",
    )
    team2 = models.ForeignKey(
        Team,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='matches_as_team2',
        verbose_name="Team 2",
    )

    score_team1 = models.IntegerField(null=True, blank=True, verbose_name="Ergebnis Team 1")
    score_team2 = models.IntegerField(null=True, blank=True, verbose_name="Ergebnis Team 2")

    winner = models.ForeignKey(
        Team,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='won_matches',
        verbose_name="Gewinner",
    )
    loser = models.ForeignKey(
        Team,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='lost_matches',
        verbose_name="Verlierer",
    )

    is_bye = models.BooleanField(default=False, verbose_name="Freilos (BYE)")
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Status",
    )

    decision_reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Entscheidungsgrund",
        help_text="Wird erfasst bei manueller Admin-Entscheidung, Disqualifikation oder Forfeit.",
    )

    next_match_winner = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='prev_matches_winner',
        verbose_name="Folgematch Sieger",
    )
    next_match_winner_slot = models.PositiveSmallIntegerField(
        default=1,
        choices=[(1, 'Team 1'), (2, 'Team 2')],
        verbose_name="Ziel-Slot Sieger",
        help_text="1 für Team 1 Slot, 2 für Team 2 Slot im Sieger-Folgematch",
    )

    next_match_loser = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='prev_matches_loser',
        verbose_name="Folgematch Verlierer",
    )
    next_match_loser_slot = models.PositiveSmallIntegerField(
        default=1,
        choices=[(1, 'Team 1'), (2, 'Team 2')],
        verbose_name="Ziel-Slot Verlierer",
        help_text="1 für Team 1 Slot, 2 für Team 2 Slot im Verlierer-Folgematch",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Turnier-Match"
        verbose_name_plural = "Turnier-Matches"
        ordering = ['bracket_type', 'round_number', 'match_number']

    @property
    def winner_advances_to(self):
        if self.next_match_winner:
            return (self.next_match_winner, self.next_match_winner_slot)
        return None

    @property
    def loser_advances_to(self):
        if self.next_match_loser:
            return (self.next_match_loser, self.next_match_loser_slot)
        return None

    @property
    def round_name(self):
        if self.bracket_type == self.BracketType.GRAND_FINAL:
            return "Grand Final"
        elif self.bracket_type == self.BracketType.GRAND_FINAL_RESET:
            return "Grand Final Reset"
        elif self.bracket_type == self.BracketType.WINNERS:
            return f"WB Round {self.round_number}"
        elif self.bracket_type == self.BracketType.LOSERS:
            return f"LB Round {self.round_number}"
        elif self.bracket_type == self.BracketType.FINAL:
            return "Finale"
        elif self.bracket_type == self.BracketType.GROUP:
            group_label = f" ({self.group_name})" if self.group_name else ""
            return f"Spieltag {self.round_number}{group_label}"
        elif self.bracket_type == self.BracketType.FFA:
            return f"FFA Runde {self.round_number}"
        return f"Runde {self.round_number}"

    def __str__(self):
        if self.bracket_type == self.BracketType.FFA:
            return f"{self.round_name} M{self.match_number} ({self.participants.count()} Teilnehmer)"
        t1 = self.team1.name if self.team1 else ("BYE" if self.is_bye else "TBD")
        t2 = self.team2.name if self.team2 else ("BYE" if (self.is_bye and not self.team2) else "TBD")
        return f"{self.round_name} M{self.match_number}: {t1} vs {t2}"


class TournamentMatchParticipant(models.Model):
    match = models.ForeignKey(
        TournamentMatch,
        on_delete=models.CASCADE,
        related_name='participants',
        verbose_name="Match",
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name='match_participations',
        verbose_name="Team / Teilnehmer",
    )
    rank = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Platzierung",
        help_text="1 für 1. Platz, 2 für 2. Platz, etc.",
    )
    score = models.IntegerField(
        default=0,
        verbose_name="Punkte / Kills / Zeit",
    )
    is_disqualified = models.BooleanField(
        default=False,
        verbose_name="Disqualifiziert",
    )
    notes = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Notizen / Details",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Match-Teilnehmer (FFA)"
        verbose_name_plural = "Match-Teilnehmer (FFA)"
        unique_together = ('match', 'team')
        ordering = ['rank', '-score', 'id']

    def __str__(self):
        rank_str = f"#{self.rank} " if self.rank else ""
        return f"{rank_str}{self.team.name} ({self.score} Pkt) in Match {self.match.id}"
