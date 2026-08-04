# configuration/context_processors.py
from django.core.cache import cache

from configuration.models import FeatureFlag, NavigationItem, SystemTranslation
from events.models import Event, EventRegistration
from seating.models import SeatingCell

# Standardtexte an einer Stelle. Fehlende Keys werden per Management-Command
# angelegt, nicht bei jedem Request.
# Standardtexte an einer Stelle. Fehlende Keys werden per Management-Command
# angelegt, nicht bei jedem Request.
DEFAULT_TEXTS = {
    'seat_card_title': 'SITZPLATZBUCHUNG',
    'seat_btn_open': 'Sitzplan öffnen',
    'seat_btn_reserve': 'Sitzplatz reservieren',
    'seat_no_event_text': 'Es gibt derzeit keine aktive Veranstaltung.',
    'seat_not_registered_text': (
        'Du bist noch nicht zur Veranstaltung angemeldet. '
        'Bitte melde dich zuerst an.'
    ),
    'seat_confirm_title': 'SITZPLATZ RESERVIEREN',
    'seat_confirm_question': (
        'Möchtest du den Sitzplatz {seat} verbindlich reservieren?'
    ),
    'seat_confirm_yes': 'Ja, reservieren',
    'seat_confirm_no': 'Abbrechen',

    # Ticket-Modul
    'ticket_eyebrow': 'DEIN TICKET',
    'ticket_default_title': 'Nächste Veranstaltung',
    'ticket_countdown_label': 'COUNTDOWN',
    'ticket_no_event': 'Sobald das nächste Event feststeht, findest du es hier.',

    # Status-Modul
    'status_header': 'AKTUELLE VERANSTALTUNG',
    'status_your_status': 'Dein Status:',
    'status_step_1': 'Nicht angemeldet',
    'status_step_2': 'Angemeldet – Zahlung ausstehend',
    'status_step_3': 'Bezahlt – bereit für den Check-in',
    'status_step_4': 'Eingecheckt',
    'status_btn_register': 'Jetzt anmelden',
    'status_no_event': 'Derzeit ist keine Veranstaltung geplant.',

    # Clan-Modul
    'clan_logo_help': 'Maximal 300x300 Pixel. Erlaubte Formate: .jpg, .jpeg, .png',
    'clan_list_title': 'Clans & Teams',
    'clan_create_btn': '+ Clan gründen',
    'clan_list_empty': 'Bisher wurden noch keine Clans gegründet.',
    'clan_members_header': 'Mitglieder',
    'clan_join_btn': 'Clan beitreten',
    'clan_leave_btn': 'Clan verlassen',

    # Navigation / Header & Footer
    'nav_login': 'Anmelden',
    'nav_register': 'Registrieren',
    'nav_logout': 'Abmelden',
    'nav_profile': 'Profil',
    'nav_admin': 'Admin',
    'nav_scanner': 'Helfer Scanner',
    'footer_copyright': '© 2026 EntailsNG – LAN Event Management CMS',

    # Dashboard Modul
    'dash_news_eyebrow': 'Aktuelles & Ankündigungen',
    'dash_news_title': 'News',
    'dash_news_pinned': '📌 WICHTIG',
    'dash_news_read_more': 'Weiterlesen →',
    'dash_news_all_link': 'Alle News & Ankündigungen anzeigen →',
    'dash_news_empty': 'Aktuell gibt es keine News.',
    'dash_seat_preview_label': 'Saalplan-Vorschau',
    'dash_seat_live_badge': 'LIVE',
    'dash_seat_occupancy_label': 'Saalbelegung',
    'dash_seat_your_seat': 'Dein Platz:',
    'dash_seat_no_seat_selected': 'Kein Sitzplatz gewählt',
    'dash_seat_not_reserved': 'Noch nicht reserviert',
    'dash_qr_modal_title': 'EINLASS QR-CODE',
    'dash_qr_modal_subtitle': 'Vorlegen beim Check-in vor Ort',
    'dash_qr_checked_in': '✓ EINGECHECKMENT',
    'dash_qr_btn_show': '📲 QR-Code anzeigen',
    'dash_qr_payment_pending': '⏳ ZAHLUNG OFFEN',

    # Auth & Profil Modul
    'auth_login_title': 'Anmelden',
    'auth_login_subtitle': 'Gib deine Zugangsdaten ein, um dich einzuloggen.',
    'auth_username_label': 'Benutzername oder E-Mail-Adresse',
    'auth_password_label': 'Passwort',
    'auth_login_btn': 'Anmelden',
    'auth_no_account': 'Noch kein Konto?',
    'auth_register_link': 'Hier registrieren',
    'auth_register_title': 'Konto erstellen',
    'auth_register_subtitle': 'Erstelle ein Konto, um an LAN-Partys teilzunehmen und Sitzplätze zu reservieren.',
    'auth_account_locked': 'Dein Konto wurde wegen 5 fehlerhafter Anmeldeversuche für 15 Minuten gesperrt. Du kannst dein Passwort zurücksetzen, um die Sperre aufzuheben.',
    'auth_email_exists': 'Diese E-Mail-Adresse wird bereits von einem anderen Konto verwendet.',
    'profile_title': 'Mein Profil',
    'profile_save_btn': 'Profil speichern',
    'profile_clan_header': 'Clan Zugehörigkeit',
    'profile_no_clan': 'Du bist aktuell in keinem Clan.',

    # News Modul
    'news_list_title': 'News & Ankündigungen',
    'news_list_empty': 'Aktuell sind keine News-Beiträge vorhanden.',

    # Info Modul
    'info_title': 'Event Information',
    'info_empty': 'Für dieses Event wurden noch keine Detail-Informationen hinterlegt.',

    # Sitzplan Modul
    'seating_plan_title': 'Sitzplan',
    'seat_legend_free': 'Frei',
    'seat_legend_prereserved': 'Vorgemerkt',
    'seat_legend_reserved': 'Reserviert (Bezahlt)',
    'seat_legend_taken': 'Besetzt (Andere)',
    'seat_legend_own': 'Dein Platz',
    'seat_stage_label': 'Bühne / Leinwand',

    # Helfer Check-in Scanner Modul
    'scanner_title': 'Vor-Ort Einlass Check-in Scanner',
    'scanner_cam_active': 'Kamera-Scanner aktiv...',
    'checkin_success_title': 'Einlass erfolgreich!',
    'checkin_failed_title': 'Einlass fehlgeschlagen!',

    # E-Mail Verifizierung (Double Opt-In) & Passwort Reset Modul
    'verify_email_title': 'E-Mail-Adresse bestätigen',
    'verify_email_subtitle': 'Wir haben dir einen 6-stelligen Bestätigungscode per E-Mail gesendet.',
    'verify_code_label': '6-stelliger Verifizierungscode',
    'verify_code_btn': 'Code bestätigen & Konto aktivieren',
    'verify_code_resend': 'Code erneut senden',
    'verify_code_expired': 'Der Bestätigungscode ist abgelaufen. Bitte fordere einen neuen Code an.',
    'verify_code_invalid': 'Ungültiger Code. Bitte überprüfe deine Eingabe.',
    'verify_code_success': 'E-Mail erfolgreich verifiziert! Dein Account ist jetzt aktiv.',
    'pw_reset_title': 'Passwort zurücksetzen',
    'pw_reset_subtitle': 'Gib deine E-Mail-Adresse ein. Wir senden dir einen Link zum Zurücksetzen deines Passworts.',
    'pw_reset_btn': 'Link anfordern',
    'pw_reset_done_title': 'E-Mail gesendet',
    'pw_reset_done_text': 'Falls ein Konto mit dieser E-Mail-Adresse existiert, haben wir dir einen Link zum Zurücksetzen gesendet.',
    'pw_reset_confirm_title': 'Neues Passwort festlegen',
    'pw_reset_confirm_btn': 'Passwort speichern',
    'pw_reset_complete_title': 'Passwort geändert!',
    'pw_reset_complete_text': 'Dein Passwort wurde erfolgreich geändert. Du kannst dich jetzt anmelden.',
}

# Template-Variable -> Übersetzungsschlüssel
TEXT_KEYS = {
    'txt_seat_card_title': 'seat_card_title',
    'txt_seat_btn_open': 'seat_btn_open',
    'txt_seat_btn_reserve': 'seat_btn_reserve',
    'txt_seat_no_event': 'seat_no_event_text',
    'txt_seat_not_registered': 'seat_not_registered_text',
    'txt_seat_confirm_title': 'seat_confirm_title',
    'txt_seat_confirm_question': 'seat_confirm_question',
    'txt_seat_confirm_yes': 'seat_confirm_yes',
    'txt_seat_confirm_no': 'seat_confirm_no',
    'txt_ticket_eyebrow': 'ticket_eyebrow',
    'txt_ticket_default_title': 'ticket_default_title',
    'txt_ticket_countdown_label': 'ticket_countdown_label',
    'txt_ticket_no_event': 'ticket_no_event',
    'txt_status_header': 'status_header',
    'txt_status_your_status': 'status_your_status',
    'txt_status_step_1': 'status_step_1',
    'txt_status_step_2': 'status_step_2',
    'txt_status_step_3': 'status_step_3',
    'txt_status_step_4': 'status_step_4',
    'txt_status_btn_register': 'status_btn_register',
    'txt_status_no_event': 'status_no_event',
    'txt_clan_logo_help': 'clan_logo_help',
}

# Füge dynamisch txt_<key> für alle DEFAULT_TEXTS hinzu
for _k in DEFAULT_TEXTS.keys():
    TEXT_KEYS[f'txt_{_k}'] = _k

TRANSLATION_CACHE_KEY = 'system_translations'
FEATURE_FLAGS_CACHE_KEY = 'feature_flags_dict'
NAV_CACHE_KEY = 'navigation_items'
CACHE_SECONDS = 300


def _load_translations():
    """Lädt alle Übersetzungen in EINER Query und cached sie."""
    texts = cache.get(TRANSLATION_CACHE_KEY)
    if texts is None:
        texts = dict(SystemTranslation.objects.values_list('key', 'text'))
        cache.set(TRANSLATION_CACHE_KEY, texts, CACHE_SECONDS)
    return texts


def _load_feature_flags():
    """Lädt alle Feature Flags in EINER Query und cached sie."""
    flags = cache.get(FEATURE_FLAGS_CACHE_KEY)
    if flags is None:
        flags = dict(FeatureFlag.objects.values_list('key', 'is_enabled'))
        cache.set(FEATURE_FLAGS_CACHE_KEY, flags, CACHE_SECONDS)
    return flags


def feature_flags(request):
    """Stellt Event-Daten, Menüpunkte, Feature-Flags und Texte in allen Templates bereit."""
    texts = _load_translations()
    features = _load_feature_flags()

    all_nav_items = cache.get_or_set(
        NAV_CACHE_KEY,
        lambda: list(
            NavigationItem.objects.filter(is_active=True).order_by(
                'order', 'id'
            )
        ),
        CACHE_SECONDS,
    )

    MODULE_FLAG_MAP = {
        'seating_plan': 'seating_module',
        'seating': 'seating_module',
        'news_list': 'news_module',
        'news': 'news_module',
        'event_info_detail': 'info_module',
        'info': 'info_module',
        'clan_list': 'clan_module',
        'clans': 'clan_module',
    }

    filtered_nav_items = [
        item for item in all_nav_items
        if features.get(MODULE_FLAG_MAP.get(item.url_name, ''), True)
    ]

    context = {
        'nav_items': filtered_nav_items,
        'features': features,
        'feature_flags': features,
        'upcoming_event': None,
        'user_registration': None,
        'is_user_registered': False,
        'user_status_step': 1,
        'user_seat_label': None,
    }

    tr_dict = {key: texts.get(key) or default for key, default in DEFAULT_TEXTS.items()}
    context['tr'] = tr_dict
    context['translations'] = tr_dict

    for var_name, key in TEXT_KEYS.items():
        context[var_name] = texts.get(key) or DEFAULT_TEXTS.get(key, '')

    upcoming_event = Event.objects.filter(is_active=True).first()
    context['upcoming_event'] = upcoming_event

    # Event Kapazität & Belegungsquote für Fortschrittsbalken berechnen (immer verfügbar)
    if upcoming_event:
        seat_cells = SeatingCell.objects.filter(
            plan__event=upcoming_event,
            cell_type=SeatingCell.CellType.SEAT,
        )
        total_seats = seat_cells.count()
        reserved_seats = seat_cells.filter(
            reservation_status__in=[
                SeatingCell.ReservationStatus.PRE_RESERVED,
                SeatingCell.ReservationStatus.RESERVED,
            ]
        ).count()
        capacity_percent = (
            int((reserved_seats / total_seats) * 100) if total_seats > 0 else 0
        )

        context['event_total_seats'] = total_seats
        context['event_reserved_seats'] = reserved_seats
        context['event_capacity_percent'] = capacity_percent

    if not (request.user.is_authenticated and upcoming_event):
        return context

    registration = (
        EventRegistration.objects.filter(
            event=upcoming_event, user=request.user
        )
        .select_related('user')
        .first()
    )
    if registration is None:
        return context

    context['user_registration'] = registration
    context['is_user_registered'] = True

    if registration.is_checked_in:
        context['user_status_step'] = 4
    elif registration.payment_status == EventRegistration.PaymentStatus.PAID:
        context['user_status_step'] = 3
    else:
        context['user_status_step'] = 2

    cell = SeatingCell.objects.filter(
        plan__event=upcoming_event, registration__user=request.user
    ).first()
    if cell:
        context['user_seat_label'] = (
            cell.seat_label or f'Pos ({cell.x},{cell.y})'
        )

    return context
