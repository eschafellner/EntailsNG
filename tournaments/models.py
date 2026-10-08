import uuid
import secrets
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils.text import slugify
from django.utils import timezone
from configuration.translations import get_translation
from .external_urls import validate_external_tournament_url


class TournamentResultLog(models.Model):
    tournament = models.ForeignKey('Tournament', on_delete=models.CASCADE, related_name='result_logs')
    match = models.ForeignKey('TournamentMatch', null=True, blank=True, on_delete=models.SET_NULL, related_name='result_logs')
    match_label = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=20, default='RESULT')
    reason = models.CharField(max_length=255, blank=True)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def get_action_display(self):
        return get_translation({'RESULT': 'results_save', 'DEPENDENCY': 'results_dependency_action',
            'START': 'results_start', 'RELEASE': 'results_release', 'CONFIRM': 'results_confirm'}.get(self.action, 'results_save'))

    @property
    def before_display(self):
        return self._display_snapshot(self.before)

    @property
    def after_display(self):
        return self._display_snapshot(self.after)

    @staticmethod
    def _display_snapshot(data):
        if data.get('removed'):
            return get_translation('results_removed')
        if 'participants' in data:
            return '\n'.join(get_translation('results_ffa_history', team=p.get('team__name', p['team_id']),
                rank=p['rank'] if p['rank'] is not None else '—', score=p['score'],
                disqualified=get_translation('tournament_ffa_dq_label') if p['is_disqualified'] else '')
                for p in data['participants'])
        if 'score_team1' in data:
            return get_translation('ux_score_summary', team1=data.get('team1', '—'), team2=data.get('team2', '—'),
                score1=data['score_team1'] if data['score_team1'] is not None else '—',
                score2=data['score_team2'] if data['score_team2'] is not None else '—', winner=data.get('winner') or '—')
        if 'status' in data:
            return Tournament(status=data['status']).get_status_display()
        if 'playoffs_released_at' in data:
            return get_translation('results_release_success')
        return '—'

    class Meta:
        ordering = ('-created_at', '-pk')
        verbose_name = 'Ergebnisprotokoll'
        verbose_name_plural = 'Ergebnisprotokolle'


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


class TournamentQuerySet(models.QuerySet):
    def visible_to(self, user):
        if self.model.can_view_drafts(user):
            return self
        return self.exclude(status=self.model.Status.DRAFT)


class Tournament(models.Model):
    objects = TournamentQuerySet.as_manager()

    @staticmethod
    def can_view_drafts(user):
        """Drafts are internal, including when a guest is assigned tournament support."""
        return bool(
            user and user.is_authenticated and user.is_active
            and not user.deleted_at and (user.is_staff or user.is_superuser)
        )

    class Mode(models.TextChoices):
        SINGLE_ELIMINATION = 'SINGLE_ELIMINATION', 'Single Elimination (KO-System)'
        DOUBLE_ELIMINATION = 'DOUBLE_ELIMINATION', 'Double Elimination (Winner + Loser Bracket)'
        LEAGUE = 'LEAGUE', 'Liga (Jeder gegen Jeden)'
        GROUP_STAGE = 'GROUP_STAGE', 'Gruppenspiele mit anschließendem KO-System'
        FFA = 'FFA', 'Alle in einem (Free-For-All / Deathmatch)'
        SWISS = 'SWISS', 'Schweizer System'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Entwurf'
        REGISTRATION_OPEN = 'OPEN', 'Anmeldung geöffnet'
        REGISTRATION_CLOSED = 'CLOSED', 'Anmeldung geschlossen'
        IN_PROGRESS = 'IN_PROGRESS', 'Turnier läuft'
        RESULTS_REVIEW = 'RESULTS_REVIEW', 'Ergebnisse prüfen'
        FINISHED = 'FINISHED', 'Beendet'
        CANCELLED = 'CANCELLED', 'Abgesagt'

    class Tiebreak(models.TextChoices):
        LEGACY = 'LEGACY', 'Punkte, Score-Differenz, Scores, Teamname'
        SHARED = 'SHARED', 'Punkte, Score-Differenz, Scores; geteilte Plätze'
        HEAD_TO_HEAD = 'HEAD_TO_HEAD', 'Punkte, direkter Vergleich, Score; geteilte Plätze'

    class RosterRule(models.TextChoices):
        STRICT = 'STRICT', 'Vollständiges Team erforderlich'
        BY_START = 'BY_START', 'Team darf bis zum Start aufgefüllt werden'
        ALLOW_INCOMPLETE = 'ALLOW_INCOMPLETE', 'Unvollständige Teams zugelassen'

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

    roster_rule = models.CharField(
        max_length=20, choices=RosterRule.choices, default=RosterRule.STRICT,
        verbose_name='Regel zur Teamgröße',
        help_text='Gilt für Anmeldung und Start. Die maximale Teamgröße bleibt bestehen; nach Turniergenerierung ist die Regel gesperrt.',
    )

    swiss_rounds = models.PositiveSmallIntegerField(default=4, verbose_name="Schweizer System: Runden",
        help_text="Vor dem Start festlegen. Bei gerader Teilnehmerzahl höchstens N−1, bei ungerader höchstens N Runden.")
    swiss_allow_draws = models.BooleanField(default=False, verbose_name="Schweizer System: Unentschieden erlauben")
    swiss_pairing_seed = models.PositiveIntegerField(null=True, blank=True, editable=False)
    play_third_place = models.BooleanField(default=False, verbose_name='Spiel um Platz 3',
        help_text='Bei Single Elimination und Gruppenphase mit Halbfinals.')
    group_qualifiers_per_group = models.PositiveSmallIntegerField(default=0,
        choices=[(0, 'Automatisch (ab 8 Teams zwei pro Gruppe)'), (1, 'Ein Team pro Gruppe'), (2, 'Zwei Teams pro Gruppe')],
        verbose_name='Qualifikanten pro Gruppe')
    standings_tiebreak = models.CharField(max_length=20, choices=Tiebreak.choices,
        default=Tiebreak.SHARED, verbose_name='Gleichstandsregel für Liga und Gruppen',
        help_text='In Gruppen entscheidet bei weiterem Gleichstand die Setzposition über die Qualifikation.')

    registration_start = models.DateTimeField(verbose_name="Anmeldebeginn")
    registration_end = models.DateTimeField(verbose_name="Anmeldeschluss")
    tournament_start = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Turnierstart",
        help_text="Beginn des Turniers. Bleibt dieses Feld leer, gilt automatisch das Ende des Anmeldeschlusses.",
    )

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

    playoffs_released_at = models.DateTimeField(null=True, blank=True, editable=False)
    results_confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    results_confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='confirmed_tournaments', editable=False)

    restarted_from = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='restart_editions', editable=False, verbose_name='Neustart von')
    restart_source_title = models.CharField(max_length=150, blank=True, editable=False, verbose_name='Originaltitel beim Neustart')
    restarted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='restarted_tournaments', editable=False, verbose_name='Neustart vorbereitet von')
    restart_reason = models.TextField(blank=True, max_length=1000, editable=False, verbose_name='Anlass für den Neustart')
    restart_request_id = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    restart_cancelled_source = models.BooleanField(default=False, editable=False, verbose_name='Original beim Neustart abgesagt')
    restart_team_snapshot = models.JSONField(default=list, blank=True, editable=False, verbose_name='Übernommene Teams beim Neustart')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Erstellt am")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Zuletzt geändert")

    class Meta:
        verbose_name = "Turnier"
        verbose_name_plural = "Turniere"
        ordering = ["-registration_start", "title"]

    def get_mode_display(self):
        from configuration.translations import get_translation
        key_map = {
            self.Mode.SINGLE_ELIMINATION: ('tournament_mode_single_elimination', 'Single Elimination (KO-System)'),
            self.Mode.DOUBLE_ELIMINATION: ('tournament_mode_double_elimination', 'Double Elimination (Winner + Loser Bracket)'),
            self.Mode.LEAGUE: ('tournament_mode_league', 'Liga (Jeder gegen Jeden)'),
            self.Mode.GROUP_STAGE: ('tournament_mode_group_stage', 'Gruppenspiele mit anschließendem KO-System'),
            self.Mode.FFA: ('tournament_mode_ffa', 'Alle in einem (Free-For-All / Deathmatch)'),
            self.Mode.SWISS: ('tournament_mode_swiss', 'Schweizer System'),
        }
        if self.mode in key_map:
            key, default = key_map[self.mode]
            return get_translation(key, default)
        return super().get_mode_display()

    def get_status_display(self):
        from configuration.translations import get_translation
        key_map = {
            self.Status.DRAFT: ('tournament_status_draft', 'Entwurf'),
            self.Status.REGISTRATION_OPEN: ('tournament_status_open', 'Anmeldung geöffnet'),
            self.Status.REGISTRATION_CLOSED: ('tournament_status_closed', 'Anmeldung geschlossen'),
            self.Status.IN_PROGRESS: ('tournament_status_running', 'Turnier läuft'),
            self.Status.RESULTS_REVIEW: ('results_review', 'Ergebnisse prüfen'),
            self.Status.FINISHED: ('tournament_status_finished', 'Beendet'),
            self.Status.CANCELLED: ('tournament_status_cancelled', 'Abgesagt'),
        }
        if self.status in key_map:
            key, default = key_map[self.status]
            return get_translation(key, default)
        return super().get_status_display()

    def get_standings_tiebreak_display(self):
        keys = {self.Tiebreak.LEGACY: 'format_tiebreak_legacy', self.Tiebreak.SHARED: 'format_tiebreak_shared',
                self.Tiebreak.HEAD_TO_HEAD: 'format_tiebreak_head_to_head'}
        return get_translation(keys.get(self.standings_tiebreak, 'format_tiebreak_shared'))

    def get_roster_rule_display(self):
        return get_translation({
            self.RosterRule.STRICT: 'roster_rule_strict',
            self.RosterRule.BY_START: 'roster_rule_by_start',
            self.RosterRule.ALLOW_INCOMPLETE: 'roster_rule_allow_incomplete',
        }.get(self.roster_rule, 'roster_rule_strict'))

    def roster_size_allowed(self, count, *, for_start=False):
        """One rule for registration, start validation and UI readiness."""
        if self.roster_rule not in self.RosterRule.values or not 1 <= count <= self.game.team_size:
            return False
        require_full = self.roster_rule == self.RosterRule.STRICT or (
            for_start and self.roster_rule == self.RosterRule.BY_START)
        return not require_full or count == self.game.team_size

    def __str__(self):
        return f"{self.title} ({self.get_mode_display()})"

    @property
    def effective_tournament_start(self):
        """
        Gibt das explizite Startdatum des Turniers zurück.
        Falls kein expliziter Start hinterlegt wurde, wird das Ende des Anmeldeschlusses verwendet.
        """
        return self.tournament_start or self.registration_end

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.pk:
            # Serialize rule changes with bracket generation and Swiss publication.
            type(self).objects.select_for_update().filter(pk=self.pk).values_list('pk', flat=True).first()
        self._validate_format_settings()
        self._validate_swiss_settings()
        if not self.slug:
            base_slug = slugify(self.title) or "turnier"
            slug_limit = self._meta.get_field('slug').max_length
            slug = base_slug[:slug_limit]
            count = 1
            while Tournament.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                suffix = f'-{count}'
                slug = base_slug[:slug_limit-len(suffix)] + suffix
                count += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def _validate_swiss_settings(self):
        if self.mode == self.Mode.SWISS and not 1 <= self.swiss_rounds <= 100:
            raise ValidationError({'swiss_rounds': 'Bitte zwischen 1 und 100 Runden festlegen.'})
        if self.pk and SwissRound.objects.filter(tournament_id=self.pk).exists():
            original = Tournament.objects.get(pk=self.pk)
            immutable = ('mode', 'event_id', 'game_id', 'swiss_rounds', 'swiss_allow_draws', 'swiss_pairing_seed')
            if any(getattr(self, field) != getattr(original, field) for field in immutable):
                raise ValidationError('Die Regeln eines gestarteten Schweizer Turniers sind festgeschrieben.')
            if original.is_generated and not self.is_generated:
                raise ValidationError('Bitte zum Zurücksetzen die Turnieraktion verwenden.')
            if original.status in (self.Status.FINISHED, self.Status.CANCELLED) and self.status != original.status:
                raise ValidationError('Ein abgeschlossenes Schweizer Turnier kann nicht wieder geöffnet werden.')
            if self.status not in (self.Status.IN_PROGRESS, self.Status.RESULTS_REVIEW, self.Status.FINISHED, self.Status.CANCELLED):
                raise ValidationError(get_translation('audit_swiss_registration_frozen', 'Die Anmeldung eines gestarteten Schweizer Turniers kann nur über die Turnieraktion wieder geöffnet werden.'))
            if self.status == self.Status.FINISHED:
                last = self.swiss_round_records.order_by('-number').first()
                if last.number != self.swiss_rounds or last.matches.exclude(status=TournamentMatch.Status.COMPLETED).exists():
                    raise ValidationError('Das Schweizer Turnier kann erst nach Abschluss der letzten Runde beendet werden.')

    def _validate_format_settings(self):
        if self.roster_rule not in self.RosterRule.values:
            raise ValidationError({'roster_rule': get_translation('roster_rule_invalid')})
        if self.group_qualifiers_per_group not in (0, 1, 2):
            raise ValidationError({'group_qualifiers_per_group': get_translation('format_invalid_qualifiers')})
        if self.standings_tiebreak not in self.Tiebreak.values:
            raise ValidationError({'standings_tiebreak': get_translation('format_invalid_tiebreak')})
        if self.pk:
            fields = ('play_third_place', 'group_qualifiers_per_group', 'standings_tiebreak', 'roster_rule')
            old = type(self).objects.filter(pk=self.pk, is_generated=True).values(*fields).first()
            if old and any(getattr(self, field) != old[field] for field in fields):
                raise ValidationError(get_translation('format_rules_frozen'))

    def clean(self):
        super().clean()
        self._validate_format_settings()
        self._validate_swiss_settings()

    @property
    def is_registration_open(self):
        now = timezone.now()
        return (
            self.status == self.Status.REGISTRATION_OPEN
            and not self._event_is_closed()
            and (self.registration_start is None or self.registration_start <= now)
            and (self.registration_end is None or now <= self.registration_end)
        )

    def _event_is_closed(self):
        """Liest den aktuellen Eventstatus, auch wenn self.event bereits geladen wurde."""
        from events.models import Event
        active_event = Event.objects.get_active()
        event = (
            active_event if active_event and active_event.pk == self.event_id
            else Event.objects.get(pk=self.event_id)
        )
        return event.effective_status in (Event.Status.FINISHED, Event.Status.CANCELLED)

    def is_managed_by(self, user):
        """
        Zentrale Autorisierungsprüfung: Prüft, ob der angegebene Benutzer
        Turnier-Administrator, Support oder System-Staff/Superuser ist.
        """
        if not user or not user.is_authenticated or not user.is_active or user.deleted_at:
            return False
        return bool(
            user.is_staff
            or user.is_superuser
            or user == self.tournament_admin
            or user == self.tournament_support
        )

    def can_register(self, user=None, team=None):
        """
        Zentrale Validierung, ob ein Team oder Spieler für dieses Turnier angemeldet werden darf.
        Rückgabe: Tuple (can_register: bool, reason: str)
        """
        now = timezone.now()

        if self.status != self.Status.REGISTRATION_OPEN:
            return False, f"Die Anmeldung für '{self.title}' ist aktuell nicht geöffnet (Status: {self.get_status_display()})."

        if self._event_is_closed():
            return False, get_translation(
                'msg_tournament_event_finished',
                'Die Veranstaltung "{event_title}" ist beendet oder abgesagt. Eine Turnieranmeldung ist nicht mehr möglich.',
                event_title=self.event.title,
            )

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

        if team:
            if self.registrations.filter(team=team).exists():
                return False, f"Das Team '{team.name}' ist bereits für dieses Turnier angemeldet."
            if not team.game or (self.game and team.game != self.game):
                return False, f"Das Team '{team.name}' ist nicht für das Spiel '{self.game.name if self.game else ''}' registriert."
            if self.game:
                accepted_count = team.get_accepted_members().count()
                if accepted_count == 0:
                    return False, get_translation('roster_empty', team=team.name)
                if accepted_count < self.game.team_size and not self.roster_size_allowed(accepted_count):
                    return False, f"Das Team '{team.name}' hat nur {accepted_count} von {self.game.team_size} erforderlichen Mitgliedern."
                if accepted_count > self.game.team_size:
                    return False, f"Das Team '{team.name}' hat {accepted_count} Mitglieder (erlaubt sind maximal {self.game.team_size})."

        return True, ""

    def registered_teams_count(self):
        if hasattr(self, 'annotated_registered_teams_count'):
            return self.annotated_registered_teams_count
        return self.registrations.count()


class ExternalTournamentQuerySet(models.QuerySet):
    def visible_to(self, user):
        if Tournament.can_view_drafts(user):
            return self
        return self.filter(status=self.model.Status.PUBLISHED)


class ExternalTournament(models.Model):
    """Event-bound listings; deliberately outside registration and result services."""
    objects = ExternalTournamentQuerySet.as_manager()

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Entwurf'
        PUBLISHED = 'PUBLISHED', 'Veröffentlicht'

    event = models.ForeignKey(
        'events.Event', on_delete=models.CASCADE, related_name='external_tournaments',
        verbose_name='Veranstaltung',
    )
    game = models.ForeignKey(
        Game, on_delete=models.PROTECT, related_name='external_tournaments', verbose_name='Spiel',
    )
    title = models.CharField(max_length=150, verbose_name='Turniertitel')
    provider_name = models.CharField(max_length=100, verbose_name='Anbietername')
    external_url = models.URLField(
        max_length=1000, validators=[validate_external_tournament_url], verbose_name='Turnieradresse',
    )
    description = models.TextField(max_length=500, blank=True, verbose_name='Kurzbeschreibung')
    mode = models.CharField(max_length=100, blank=True, verbose_name='Turniermodus')
    tournament_start = models.DateTimeField(null=True, blank=True, verbose_name='Turnierstart')
    registration_end = models.DateTimeField(null=True, blank=True, verbose_name='Anmeldeschluss')
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT, verbose_name='Veröffentlichungszustand',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Erstellt am')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Zuletzt geändert')

    class Meta:
        verbose_name = 'Externes Turnier'
        verbose_name_plural = 'Externe Turniere'
        ordering = ('title', 'pk')

    def __str__(self):
        return self.title

    def get_status_display(self):
        return get_translation({
            self.Status.DRAFT: 'external_tournament_status_draft',
            self.Status.PUBLISHED: 'external_tournament_status_published',
        }.get(self.status, 'external_tournament_status_draft'))

    @property
    def safe_external_url(self):
        # Also protect rendering after imports or QuerySet.update() bypass validation.
        try:
            validate_external_tournament_url(self.external_url)
        except ValidationError:
            return ''
        return self.external_url

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


def generate_invite_code():
    return secrets.token_hex(4).upper()


class Team(models.Model):
    name = models.CharField(max_length=32, verbose_name="Teamname")
    slug = models.SlugField(max_length=100, unique=True, blank=True, verbose_name="URL-Slug")
    tag = models.CharField(max_length=5, blank=True, verbose_name="Clan-/Team-Tag")
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
        if self.tag:
            self.tag = self.tag.strip().upper()
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

    @property
    def accepted_members_count(self):
        """
        Liefert die Anzahl der akzeptierten Mitglieder.
        Verwendet bevorzugt Vor-Annotationen oder den Prefetch-Cache, um N+1-Queries zu vermeiden.
        """
        if hasattr(self, 'annotated_accepted_members_count'):
            return self.annotated_accepted_members_count
        if hasattr(self, '_prefetched_objects_cache') and 'memberships' in self._prefetched_objects_cache:
            return sum(1 for m in self.memberships.all() if m.status == TeamMember.Status.ACCEPTED)
        return self.memberships.filter(status=TeamMember.Status.ACCEPTED).count()

    @property
    def pending_members_count(self):
        """
        Liefert die Anzahl der ausstehenden Beitrittsanfragen.
        Verwendet den Prefetch-Cache, falls verfügbar.
        """
        if hasattr(self, '_prefetched_objects_cache') and 'memberships' in self._prefetched_objects_cache:
            return sum(1 for m in self.memberships.all() if m.status == TeamMember.Status.PENDING)
        return self.memberships.filter(status=TeamMember.Status.PENDING).count()

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
        ).exclude(
            tournament__status__in=[Tournament.Status.FINISHED, Tournament.Status.CANCELLED]
        ).exists()

    def delete(self, *args, **kwargs):
        force = kwargs.pop('force', False)
        if self.is_in_active_tournament():
            if not force:
                from django.core.exceptions import ValidationError
                raise ValidationError(
                    f"Das Team '{self.name}' kann nicht gelöscht werden, da es in einem laufenden oder generierten Turnier registriert ist."
                )
            from tournaments.services import forfeit_team_in_active_tournaments
            forfeit_team_in_active_tournaments(self, reason=f"Walkover: Team '{self.name}' gelöscht")
        # Swiss standings depend on every historical opponent, including withdrawals.
        if self.tournament_registrations.filter(tournament__mode=Tournament.Mode.SWISS,
                                                tournament__is_generated=True).exists():
            self.is_archived = True
            self.save(update_fields=['is_archived'])
            return
        super().delete(*args, **kwargs)

    def leave_team(self, user, force_forfeit=False):
        """
        Entfernt einen User aus dem Team.
        Wenn der Kapitän austritt, geht die Kapitänswürde an ein beliebiges anderes aktives Mitglied.
        Verlässt das letzte Mitglied das Team, wird das Team gelöscht.
        Bei aktivem Turnier: Mit force_forfeit=True werden offene Matches als Walkover abgewickelt.
        """
        membership = self.memberships.filter(user=user).first()
        if not membership:
            return False

        if membership.status == TeamMember.Status.ACCEPTED and self.is_in_active_tournament():
            accepted_count = self.memberships.filter(status=TeamMember.Status.ACCEPTED).count()
            required_size = self.game.team_size if self.game and self.game.team_size else 1
            if (accepted_count - 1) < required_size or accepted_count <= 1:
                if not force_forfeit:
                    return 'in_active_tournament'
                from tournaments.services import forfeit_team_in_active_tournaments
                forfeit_team_in_active_tournaments(self, reason=f"Walkover: Aufgabe durch Austritt von {user.username}")

        membership.delete()

        remaining_memberships = self.memberships.filter(status=TeamMember.Status.ACCEPTED).order_by('joined_at')
        if not remaining_memberships.exists():
            self.delete(force=True)
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
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='direct_team_additions', verbose_name="Hinzugefügt von", editable=False,
    )

    class Meta:
        verbose_name = "Team-Mitgliedschaft"
        verbose_name_plural = "Team-Mitgliedschaften"
        unique_together = ('team', 'user')
        ordering = ['role', 'joined_at']

    def get_role_display(self):
        from configuration.translations import get_translation
        key_map = {
            self.Role.CAPTAIN: ('team_role_captain', 'Kapitän'),
            self.Role.MEMBER: ('team_role_member', 'Mitglied'),
        }
        if self.role in key_map:
            key, default = key_map[self.role]
            return get_translation(key, default)
        return super().get_role_display()

    def get_status_display(self):
        from configuration.translations import get_translation
        key_map = {
            self.Status.ACCEPTED: ('team_member_status_accepted', 'Mitglied'),
            self.Status.PENDING: ('team_member_status_pending', 'Anfrage ausstehend'),
        }
        if self.status in key_map:
            key, default = key_map[self.status]
            return get_translation(key, default)
        return super().get_status_display()

    def __str__(self):
        return f"{self.user.username} @ {self.team.name} ({self.get_role_display()})"


class TeamInvitation(models.Model):
    """Personal invitations are separate from applications and accepted rosters."""
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Offen'
        ACCEPTED = 'ACCEPTED', 'Angenommen'
        DECLINED = 'DECLINED', 'Abgelehnt'
        WITHDRAWN = 'WITHDRAWN', 'Zurückgezogen'
        EXPIRED = 'EXPIRED', 'Ungültig geworden'

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='invitations')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='team_invitations', verbose_name="Eingeladener Spieler")
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='sent_team_invitations', verbose_name="Eingeladen von")
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, null=True, blank=True,
        related_name='team_invitations', verbose_name="Veranstaltung bei Einladung")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Team-Einladung"
        verbose_name_plural = "Team-Einladungen"
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(
            fields=['team', 'user'], condition=models.Q(status='PENDING'),
            name='unique_pending_team_invitation',
        )]


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
    draw_clan = models.ForeignKey('clans.Clan', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='tournament_draw_registrations', verbose_name='Clan für die Auslosung',
        help_text='Von der Turnierleitung bestätigte Clan-Zuordnung für dieses Turnier.')
    group_name = models.CharField(max_length=20, blank=True, verbose_name="Gruppe (z.B. Gruppe A)")
    score = models.IntegerField(default=0, verbose_name="Punkte / Kills (für FFA)")
    is_forfeited = models.BooleanField(
        default=False,
        verbose_name="Aufgegeben / Zurückgezogen",
        help_text="Wird auf True gesetzt, wenn das Team das Turnier aufgibt oder vorzeitig ausscheidet.",
    )

    class Meta:
        verbose_name = "Turnieranmeldung"
        verbose_name_plural = "Turnieranmeldungen"
        unique_together = ('tournament', 'team')
        ordering = ['registered_at']

    def __str__(self):
        return f"{self.team.name} -> {self.tournament.title}"

    def clean(self):
        super().clean()
        if self.pk and self.tournament_id and Tournament.objects.filter(pk=self.tournament_id, is_generated=True).exists():
            original_clan = type(self).objects.values_list('draw_clan_id', flat=True).get(pk=self.pk)
            if self.draw_clan_id != original_clan:
                raise ValidationError(get_translation('draw_unavailable'))
        started_swiss = self.tournament_id and Tournament.objects.filter(
            pk=self.tournament_id, mode=Tournament.Mode.SWISS, is_generated=True).exists()
        historical_entry = self.pk and self.swiss_entries.exists()
        if started_swiss or historical_entry:
            if not self.pk:
                raise ValidationError('Nach dem Start sind keine weiteren Schweizer Teilnehmer möglich.')
            old = TournamentRegistration.objects.get(pk=self.pk)
            if (old.team_id, old.tournament_id, old.seed) != (self.team_id, self.tournament_id, self.seed):
                raise ValidationError('Teilnehmer und Startreihenfolge sind bereits festgeschrieben.')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class TournamentDraw(models.Model):
    """Immutable publication snapshot; reset/restart never remove this history."""
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name='draw_logs')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    request_id = models.UUIDField(unique=True, editable=False)
    mode = models.CharField(max_length=30)
    method = models.CharField(max_length=20)
    random_seed = models.PositiveIntegerField()
    respect_seeds = models.BooleanField(default=True)
    avoid_clans = models.BooleanField(default=True)
    input_digest = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)
    conflict_count = models.PositiveIntegerField(default=0)
    reason = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        verbose_name = 'Turnierauslosung'
        verbose_name_plural = 'Turnierauslosungen'

    def get_method_display(self):
        return get_translation(f'draw_method_{self.method}')

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(get_translation('draw_history'))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(get_translation('draw_history'))


class TournamentMatch(models.Model):
    class BracketType(models.TextChoices):
        WINNERS = 'WINNERS', 'Winner Bracket'
        LOSERS = 'LOSERS', 'Loser Bracket'
        GRAND_FINAL = 'GRAND_FINAL', 'Grand Final'
        GRAND_FINAL_RESET = 'GRAND_FINAL_RESET', 'Grand Final Reset'
        FINAL = 'FINAL', 'Finale'
        THIRD_PLACE = 'THIRD_PLACE', 'Spiel um Platz 3'
        GROUP = 'GROUP', 'Gruppenspiel'
        FFA = 'FFA', 'Free For All'
        SWISS = 'SWISS', 'Schweizer Runde'

    class ResultType(models.TextChoices):
        PLAYED = 'PLAYED', 'Gespielt'
        BYE = 'BYE', 'Freilos'
        WALKOVER = 'WALKOVER', 'Kampfloser Sieg'
        DOUBLE_FORFEIT = 'DOUBLE_FORFEIT', 'Beide Teilnehmer zurückgezogen'

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
    swiss_round = models.ForeignKey('SwissRound', null=True, blank=True, on_delete=models.CASCADE, related_name='matches')
    result_type = models.CharField(max_length=20, choices=ResultType.choices, default=ResultType.PLAYED,
                                   verbose_name="Ergebnisart")
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
        constraints = [models.UniqueConstraint(fields=['tournament', 'round_number', 'match_number'],
            condition=models.Q(bracket_type='SWISS'), name='unique_swiss_match_number')]

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

    def get_status_display(self):
        from configuration.translations import get_translation
        key_map = {
            self.Status.PENDING: ('tournament_match_status_pending', 'Ausstehend'),
            self.Status.READY: ('tournament_match_status_ready', 'Bereit'),
            self.Status.IN_PROGRESS: ('tournament_match_status_in_progress', 'Läuft'),
            self.Status.COMPLETED: ('tournament_match_status_completed', 'Beendet'),
        }
        if self.status in key_map:
            key, default = key_map[self.status]
            return get_translation(key, default)
        return super().get_status_display()

    def get_bracket_type_display(self):
        from configuration.translations import get_translation
        key_map = {
            self.BracketType.WINNERS: ('tournament_bracket_winners', 'Winner Bracket'),
            self.BracketType.LOSERS: ('tournament_bracket_losers', 'Loser Bracket'),
            self.BracketType.GRAND_FINAL: ('tournament_bracket_grand_final', 'Grand Final'),
            self.BracketType.GRAND_FINAL_RESET: ('tournament_bracket_grand_final_reset', 'Grand Final Reset'),
            self.BracketType.FINAL: ('tournament_bracket_final', 'Finale'),
            self.BracketType.THIRD_PLACE: ('format_third_place', 'Spiel um Platz 3'),
            self.BracketType.GROUP: ('tournament_bracket_group', 'Gruppenspiel'),
            self.BracketType.FFA: ('tournament_bracket_ffa', 'Free For All'),
            self.BracketType.SWISS: ('tournament_bracket_swiss', 'Schweizer Runde'),
        }
        if self.bracket_type in key_map:
            key, default = key_map[self.bracket_type]
            return get_translation(key, default)
        return super().get_bracket_type_display()

    @property
    def round_name(self):
        if self.bracket_type == self.BracketType.THIRD_PLACE:
            return get_translation('format_third_place')
        if self.bracket_type == self.BracketType.GRAND_FINAL:
            return "Grand Final"
        elif self.bracket_type == self.BracketType.GRAND_FINAL_RESET:
            return "Grand Final Reset"
        elif self.bracket_type == self.BracketType.WINNERS:
            if self.tournament.mode == Tournament.Mode.SINGLE_ELIMINATION:
                next_match = self.next_match_winner
                if next_match and next_match.bracket_type == self.BracketType.FINAL:
                    return get_translation('format_semifinal')
                if next_match and next_match.next_match_winner and next_match.next_match_winner.bracket_type == self.BracketType.FINAL:
                    return get_translation('format_quarterfinal')
                return get_translation('format_ko_round', number=self.round_number)
            return get_translation('format_winner_round', number=self.round_number)
        elif self.bracket_type == self.BracketType.LOSERS:
            return f"LB Round {self.round_number}"
        elif self.bracket_type == self.BracketType.FINAL:
            return get_translation('format_semifinal' if self.next_match_winner_id else 'format_final')
        elif self.bracket_type == self.BracketType.GROUP:
            group_label = f" ({self.group_name})" if self.group_name else ""
            return f"Spieltag {self.round_number}{group_label}"
        elif self.bracket_type == self.BracketType.FFA:
            return f"FFA Runde {self.round_number}"
        elif self.bracket_type == self.BracketType.SWISS:
            return f"Schweizer Runde {self.round_number}"
        return f"Runde {self.round_number}"

    def __str__(self):
        if self.bracket_type == self.BracketType.FFA:
            return f"{self.round_name} M{self.match_number} ({self.participants.count()} Teilnehmer)"
        t1 = self.team1.name if self.team1 else ("BYE" if self.is_bye else "TBD")
        t2 = self.team2.name if self.team2 else ("BYE" if (self.is_bye and not self.team2) else "TBD")
        return f"{self.round_name} M{self.match_number}: {t1} vs {t2}"


class SwissRound(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name='swiss_round_records')
    number = models.PositiveSmallIntegerField(verbose_name='Runde')
    published_at = models.DateTimeField(default=timezone.now, verbose_name='Veröffentlicht am')
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    input_digest = models.CharField(max_length=64)
    standings_snapshot = models.JSONField(default=list)
    repeat_pairings_approved = models.BooleanField(default=False, verbose_name='Wiederholungen ausdrücklich freigegeben')

    class Meta:
        ordering = ['number']
        constraints = [models.UniqueConstraint(fields=['tournament', 'number'], name='unique_swiss_round')]

    def __str__(self):
        return f'{self.tournament.title} – Runde {self.number}'


class SwissRoundEntry(models.Model):
    round = models.ForeignKey(SwissRound, on_delete=models.CASCADE, related_name='entries')
    match = models.ForeignKey(TournamentMatch, on_delete=models.CASCADE, related_name='swiss_entries')
    registration = models.ForeignKey(TournamentRegistration, on_delete=models.RESTRICT, related_name='swiss_entries')
    team = models.ForeignKey(Team, on_delete=models.RESTRICT, related_name='swiss_entries')
    seed = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['round', 'team'], name='unique_swiss_round_team')]


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
