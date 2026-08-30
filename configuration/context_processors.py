from django.core.cache import cache
from django.utils.functional import SimpleLazyObject

from configuration.models import NavigationItem, SiteCustomization, SystemTranslation
from events.models import Event, EventRegistration
from seating.services import (
    get_event_capacity_stats,
    invalidate_event_capacity_cache,
    CAPACITY_CACHE_KEY_PREFIX,
)  # Re-Export für Rückwärtskompatibilität


DEFAULT_TEXTS = {
    # Allgemeine Schaltflächen & Aktionen
    'skip_to_content': 'Zum Inhalt springen',
    'btn_close': 'Schließen',
    'btn_cancel': 'Abbrechen',
    'btn_save': 'Speichern',
    'btn_back': '← Zurück',
    'btn_back_to_home': '🏠 Zur Startseite',
    'btn_accept': '✓ Akzeptieren',
    'btn_reject': '✕ Ablehnen',
    'form_fix_errors': 'Bitte korrigiere folgende Fehler:',
    'nav_more': 'Mehr',
    'nav_more_modal_title': 'Weitere Menüpunkte',
    'email_warning_open_settings': 'Einstellungen öffnen →',

    # Fehlerseiten
    'error_403_title': 'Zugriff verweigert',
    'error_403_text': 'Du hast nicht die erforderlichen Rechte, um auf diese Seite zuzugreifen.',
    'error_404_title': 'Seite nicht gefunden',
    'error_404_text': 'Die von dir aufgerufene Adresse existiert leider nicht oder wurde verschoben.',

    # Rechtliches
    'legal_eyebrow': 'RECHTLICHE HINWEISE',
    'nav_legal_impressum': 'Impressum',
    'nav_legal_datenschutz': 'Datenschutz',

    # Navigation / Header & Footer
    'nav_login': 'Anmelden',
    'nav_register': 'Registrieren',
    'nav_logout': 'Abmelden',
    'nav_profile': 'Profil',
    'nav_admin': 'Admin',
    'nav_scanner': 'Helfer Scanner',
    'footer_copyright': '© 2026 EntailsNG – LAN Event Management CMS',

    # Dashboard Modul
    'dash_page_title': 'Übersicht',
    'dash_event_eyebrow': 'Veranstaltung',
    'dash_news_eyebrow': 'Aktuelles & Ankündigungen',
    'dash_news_title': 'News',
    'dash_news_pinned': '📌 WICHTIG',
    'dash_news_read_more': 'Weiterlesen →',
    'dash_news_details_link': 'Details lesen →',
    'dash_news_all_link': 'Alle News & Ankündigungen anzeigen →',
    'dash_news_empty': 'Aktuell gibt es keine News.',
    'dash_seat_preview_label': 'Saalplan-Vorschau',
    'dash_seat_live_badge': 'LIVE',
    'dash_seat_occupancy_label': 'Saalbelegung',
    'dash_seat_your_seat': 'Dein Platz:',
    'dash_seat_no_seat_selected': 'Kein Sitzplatz gewählt',
    'dash_seat_not_reserved': 'Noch nicht reserviert',
    'dash_seat_not_assigned': 'Noch nicht zugewiesen',
    'dash_seat_minimap_loading': 'Mini-Map lädt...',
    'dash_seat_plan_not_configured': 'Saalplan noch nicht konfiguriert',
    'dash_seats_unit': 'Plätze',
    'dash_guest_label': 'Gast',
    'dash_guest_fallback': 'Gast',
    'dash_seat_label_title': 'Sitzplatz',
    'dash_qr_modal_title': 'EINLASS QR-CODE',
    'dash_qr_modal_eyebrow': 'EINLASS QR-CODE',
    'dash_qr_modal_subtitle': 'Vorlegen beim Check-in vor Ort',
    'dash_qr_checked_in': '✓ EINGECHECKT',
    'dash_status_checked_in': '✓ EINGECHECKT',
    'dash_qr_btn_show': '📲 QR-Code anzeigen',
    'dash_btn_show_ticket': '📲 QR-Code anzeigen',
    'dash_qr_payment_pending': '⏳ ZAHLUNG OFFEN',
    'dash_ticket_code_label': 'Ticket-Code (Für manuelle Eingabe)',
    'dash_btn_show_payment_qr': 'QR-Code für Banking-App anzeigen',
    'dash_btn_show_payment_qr_short': 'Zahlungs-QR anzeigen',
    'dash_payment_modal_eyebrow': 'SEPA-Überweisung per GiroCode / QR',
    'dash_payment_modal_title': 'Zahlung per Banking-App',
    'dash_payment_modal_subtitle': 'Scanne diesen QR-Code mit deiner Banking-App (Sparkasse, Volksbank, DKB, N26, ING etc.), um die Überweisung vorausgefüllt durchzuführen.',
    'dash_payment_manual_data_title': 'Überweisungsdaten für manuelle Eingabe:',
    'dash_payment_recipient_label': 'Empfänger:',
    'dash_payment_iban_label': 'IBAN:',
    'dash_payment_bic_label': 'BIC:',
    'dash_payment_amount_label': 'Betrag:',
    'dash_payment_amount_open': 'Frei wählbar',
    'dash_payment_purpose_label': 'Verwendungszweck:',

    # Ticket-Modul
    'ticket_eyebrow': 'DEIN TICKET',
    'ticket_default_title': 'Nächste Veranstaltung',
    'ticket_countdown_label': 'COUNTDOWN',
    'ticket_no_event': 'Sobald das nächste Event feststeht, findest du es hier.',
    'ticket_expired_eyebrow': 'VERANSTALTUNG BEENDET',
    'ticket_expired_badge': 'BEENDET',
    'ticket_expired_status': 'EVENT BEENDET',
    'ticket_expired_box_text': 'Veranstaltung beendet',
    'ticket_cd_days': 'Tage',
    'ticket_cd_hours': 'Std',
    'ticket_cd_minutes': 'Min',
    'ticket_cd_seconds': 'Sek',

    # Status-Modul
    'status_header': 'AKTUELLE VERANSTALTUNG',
    'status_your_status': 'Dein Status:',
    'status_step_1': 'Nicht angemeldet',
    'status_step_2': 'Angemeldet – Zahlung ausstehend',
    'status_step_3': 'Bezahlt – bereit für den Check-in',
    'status_step_4': 'Eingecheckt',
    'status_paid_badge': 'Bezahlt',
    'status_pending_badge': 'Offen',
    'status_btn_register': 'Jetzt anmelden',
    'status_no_event': 'Derzeit ist keine Veranstaltung geplant.',
    'status_event_draft': '📝 Event befindet sich noch im Entwurf',
    'status_event_cancelled': '🚫 Event wurde abgesagt',
    'status_event_finished': '🏁 Event ist beendet',
    'status_event_closed': '🔒 Anmeldung aktuell geschlossen',
    'status_event_full': '⚠️ Event ist ausgebucht',
    'status_ticket_category_select': 'Ticketkategorie wählen:',

    # Sitzplatz Modul
    'seat_card_title': 'SITZPLATZBUCHUNG',
    'seating_plan_title': 'Sitzplan',
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
    'seat_legend_free': 'Frei',
    'seat_legend_prereserved': 'Vorgemerkt',
    'seat_legend_reserved': 'Reserviert (Bezahlt)',
    'seat_legend_taken': 'Besetzt (Andere)',
    'seat_legend_own': 'Dein Platz',
    'seat_legend_clan': 'Dein Clan',
    'seat_legend_blocked': 'Gesperrt',
    'seat_stage_label': 'Bühne / Leinwand',
    'seat_drag_zoom_hint': '💡 Ziehen zum Verschieben • Scrollen zum Zoomen',
    'seat_fit_btn': 'Einpassen',
    'seat_loading_text': 'Sitzplan wird geladen...',
    'seat_no_event_title': 'Derzeit gibt es kein aktives/geplantes Event',
    'seat_no_event_subtitle': 'Schau gerne bald wieder vorbei! Sobald die nächste Veranstaltung angekündigt wird, kannst du dir hier deinen Sitzplatz reservieren.',
    'seating_btn_fit': 'Einpassen',
    'seating_controls_hint': 'Ziehen zum Verschieben • Scrollen zum Zoomen',
    'seating_loading': 'Sitzplan wird geladen...',
    'seating_no_event_desc': 'Schau gerne bald wieder vorbei! Sobald die nächste Veranstaltung angekündigt wird, kannst du dir hier deinen Sitzplatz reservieren.',
    'seating_no_event_title': 'Derzeit gibt es kein aktives/geplantes Event',

    # Auth & Profil Modul
    'auth_login_title': 'Anmelden',
    'auth_login_subtitle': 'Gib deine Zugangsdaten ein, um dich einzuloggen.',
    'auth_username_label': 'Benutzername oder E-Mail-Adresse',
    'auth_password_label': 'Passwort',
    'auth_login_btn': 'Anmelden',
    'auth_login_invalid_credentials': 'Benutzername/E-Mail-Adresse oder Passwort ist falsch. Bitte versuche es erneut.',
    'auth_forgot_password': 'Passwort vergessen?',
    'auth_no_account': 'Noch kein Konto?',
    'auth_register_link': 'Hier registrieren',
    'auth_register_title': 'Konto erstellen',
    'auth_register_subtitle': 'Erstelle ein Konto, um an LAN-Partys teilzunehmen und Sitzplätze zu reservieren.',
    'auth_registration_disabled_title': 'Anmeldung vorübergehend pausiert',
    'auth_username_nick_label': 'Benutzername (Nick):',
    'auth_email_label': 'E-Mail-Adresse:',
    'auth_birthday_label': 'Geburtsdatum:',
    'auth_password_confirm_label': 'Passwort bestätigen:',
    'auth_register_btn': 'Konto erstellen & Anmelden',
    'auth_already_have_account': 'Du hast bereits ein Konto?',
    'auth_login_link': 'Hier anmelden',
    'auth_back_to_login': '← Zurück zur Anmeldung',
    'auth_new_password_label': 'Neues Passwort',
    'auth_new_password_confirm_label': 'Neues Passwort (Bestätigung)',
    'auth_account_locked': 'Dein Konto wurde wegen 5 fehlerhafter Anmeldeversuche für 15 Minuten gesperrt. Du kannst dein Passwort zurücksetzen, um die Sperre aufzuheben.',
    'auth_email_exists': 'Diese E-Mail-Adresse wird bereits von einem anderen Konto verwendet.',
    'profile_title': 'Mein Profil',
    'profile_save_btn': 'Profil speichern',
    'profile_clan_header': 'Clan Zugehörigkeit',
    'profile_no_clan': 'Du bist aktuell in keinem Clan.',
    'profile_account_eyebrow': 'Benutzerkonto',
    'profile_hello': 'Hallo',
    'profile_role_label': 'Rolle',
    'profile_member_since_label': 'Mitglied seit',
    'profile_masterdata_eyebrow': 'Stammdaten',
    'profile_edit_title': 'Profil bearbeiten',
    'profile_username_cannot_change': 'Der Username kann nicht geändert werden.',
    'profile_security_eyebrow': 'Sicherheit',
    'profile_change_password_title': 'Passwort ändern',
    'profile_current_password_label': 'Aktuelles Passwort:',
    'profile_new_password_label': 'Neues Passwort:',
    'profile_new_password_confirm_label': 'Neues Passwort bestätigen:',
    'profile_update_password_btn': 'Passwort Aktualisieren',
    'profile_history_eyebrow': 'Historie',
    'profile_my_registrations_title': 'Meine Event-Anmeldungen & Tickets',
    'profile_registered_at_label': 'Angemeldet am:',
    'profile_no_registrations': 'Du bist aktuell für noch keine Veranstaltung angemeldet.',

    # E-Mail Verifizierung (Double Opt-In) & Passwort Reset Modul
    'verify_email_title': 'E-Mail-Adresse bestätigen',
    'verify_email_subtitle': 'Wir haben dir einen 6-stelligen Bestätigungscode per E-Mail gesendet.',
    'verify_code_label': '6-stelliger Verifizierungscode',
    'verify_code_btn': 'Code bestätigen & Konto aktivieren',
    'verify_code_resend': 'Code erneut senden',
    'verify_code_expired': 'Der Bestätigungscode ist abgelaufen. Bitte fordere einen neuen Code an.',
    'verify_code_invalid': 'Ungültiger Code. Bitte überprüfe deine Eingabe.',
    'verify_code_success': 'E-Mail erfolgreich verifiziert! Dein Account ist jetzt aktiv.',
    'verify_code_expires_in': '⏳ Code verfällt in:',
    'verify_code_expired_badge': 'ABGELAUFEN',
    'pw_reset_title': 'Passwort zurücksetzen',
    'pw_reset_subtitle': 'Gib deine E-Mail-Adresse ein. Wir senden dir einen Link zum Zurücksetzen deines Passworts.',
    'pw_reset_btn': 'Link anfordern',
    'pw_reset_done_title': 'E-Mail gesendet',
    'pw_reset_done_text': 'Falls ein Konto mit dieser E-Mail-Adresse existiert, haben wir dir einen Link zum Zurücksetzen gesendet.',
    'pw_reset_confirm_title': 'Neues Passwort festlegen',
    'pw_reset_confirm_subtitle': 'Gib dein neues Passwort zweimal ein, um es zu speichern.',
    'pw_reset_confirm_btn': 'Passwort speichern',
    'pw_reset_complete_title': 'Passwort geändert!',
    'pw_reset_complete_text': 'Dein Passwort wurde erfolgreich geändert. Du kannst dich jetzt anmelden.',
    'pw_reset_invalid_link_title': 'Link ungültig oder abgelaufen',
    'pw_reset_invalid_link_text': 'Dieser Passwort-Reset-Link ist ungültig oder wurde bereits verwendet. Bitte fordere einen neuen Link an.',
    'pw_reset_request_new_link': 'Neuen Link anfordern',

    # Clan-Modul
    'clan_logo_help': 'Maximal 300x300 Pixel. Erlaubte Formate: .jpg, .jpeg, .png',
    'clan_list_title': 'Clans & Teams',
    'clan_list_subtitle': 'Alle registrierten Gaming-Clans & Teams im Überblick',
    'clan_create_btn': '+ Clan gründen',
    'clan_list_empty': 'Bisher wurden noch keine Clans gegründet.',
    'clan_members_header': 'Mitglieder',
    'clan_join_btn': 'Clan beitreten',
    'clan_leave_btn': 'Clan verlassen',
    'clan_eyebrow': 'Community',
    'clan_my_clan_btn': 'Mein Clan',
    'clan_view_profile_link': 'Clanprofil ansehen →',
    'clan_profile_title': 'Clanprofil',
    'clan_edit_btn': 'Clan bearbeiten',
    'clan_admin_management_eyebrow': 'Admin-Verwaltung',
    'clan_pending_requests_title': 'Offene Beitrittsanfragen',
    'clan_requested_at_label': 'Angefragt am:',
    'clan_roster_eyebrow': 'Roster',
    'clan_members_title': 'Clan-Mitglieder',
    'clan_admin_badge': 'Clan-Admin',
    'clan_joined_at_label': 'Beigetreten:',
    'clan_make_admin_btn': 'Admin machen',
    'clan_kick_btn': 'Kick',
    'clan_direct_join_eyebrow': 'Direktbeitritt',
    'clan_join_with_password_title': 'Mit Passwort beitreten',
    'clan_password_label': 'Clan-Passwort:',
    'clan_join_now_btn': 'Sofort beitreten',
    'clan_application_eyebrow': 'Bewerbung',
    'clan_request_join_title': 'Beitrittsanfrage stellen',
    'clan_request_join_desc': 'Du kennst das Passwort nicht? Sende dem Clan-Admin eine Beitrittsanfrage.',
    'clan_request_pending_badge': 'Beitrittsanfrage gesendet (Warte auf Admin-Bestätigung)',
    'clan_send_request_btn': 'Anfrage senden',
    'clan_management_eyebrow': 'Clan-Verwaltung',
    'clan_name_label': 'Clanname:',
    'clan_website_label': 'Website URL (optional):',
    'clan_logo_label': 'Clan-Logo (optional):',
    'clan_password_for_join_label': 'Clan-Passwort für Beitritt:',
    'clan_save_btn': 'Clan Speichern',

    # Turniere & Teams Modul
    'tournament_list_title': 'Gaming Turniere',
    'tournament_eyebrow': 'Esports & Gaming',
    'tournament_list_heading': 'Turniere & Wettbewerbe',
    'tournament_list_for_event': 'Offizielle Turniere für',
    'tournament_list_subtitle': 'Alle geplanten Turniere im Überblick',
    'tournament_checkin_eligible': 'Vor Ort eingecheckt (Berechtigt)',
    'tournament_checkin_needed': 'Nicht eingecheckt (Check-in am Einlass nötig)',
    'tournament_teammanager_btn': 'Teammanager öffnen',
    'tournament_status_open': 'Anmeldephase',
    'tournament_status_running': 'Läuft aktuell',
    'tournament_status_finished': 'Beendet',
    'tournament_teams_label': 'Teams',
    'tournament_reg_deadline_label': 'Anmeldeschluss:',
    'tournament_admin_label': 'Admin:',
    'tournament_register_btn': 'Jetzt anmelden →',
    'tournament_details_btn': 'Details & Baum →',
    'tournament_empty_list': '🕹️ Aktuell sind keine Turniere für diese Veranstaltung angelegt.',
    'tournament_tab_bracket': '🏆 Turnierbaum & Matches',
    'tournament_tab_preview': '👁️ Vorschau',
    'tournament_tab_teams': '👥 Angemeldete Teams',
    'tournament_tab_rules': '📜 Regeln & Info',
    'tournament_history_title': 'Turnierverlauf',
    'tournament_league_table': '📊 Ligatabelle',
    'tournament_schedule': '📅 Spielplan & Begegnungen',
    'tournament_group_matches': '⚔️ Gruppenmatches & KO-Phase',
    'tournament_ffa_standings': '🏆 Free For All – Gesamtwertung',
    'tournament_rules_title': 'Regeln & Turnier-Details',
    'team_manager_title': 'Teammanager',
    'team_manager_eyebrow': 'Esports & Teams',
    'team_manager_subtitle': 'Erstelle Teams für Turniere, lade Freunde per Einladungscode ein oder tritt bestehenden Teams bei.',
    'team_create_btn': 'Neues Team gründen',
    'team_join_by_code_title': 'Einladungscode eingeben',
    'team_join_btn': 'Team beitreten',
    'team_my_teams_heading': 'Meine Teams',
    'team_active_teams_tab': 'Aktuelle Teams',
    'team_archived_teams_tab': 'Archivierte Teams',
    'team_leave_btn': 'Team verlassen',
    'team_apply_btn': 'Für Team bewerben',
    'team_invite_code_title': 'Einladungscode für Teammitglieder',
    'team_invite_code_desc': 'Teile diesen Code mit deinen Mitspielern. Wer den Code eingibt, tritt dem Team sofort bei.',
    'team_copy_clipboard_btn': 'In Zwischenablage kopieren',
    'team_copy_invite_code': 'In Zwischenablage kopieren',
    'team_invite_code_copied': 'Code in Zwischenablage kopiert!',
    'team_members_heading': 'Teammitglieder',
    'team_pending_applications': 'Ausstehende Bewerbungen',
    'team_reactivate_title': 'Team reaktivieren',
    'team_reactivate_btn': 'Reaktivieren',

    # News Modul
    'news_list_title': 'News & Ankündigungen',
    'news_list_empty': 'Aktuell sind keine News-Beiträge vorhanden.',
    'news_author_by': 'von',

    # Info Modul
    'info_title': 'Event Information',
    'info_empty': 'Für dieses Event wurden noch keine Detail-Informationen hinterlegt.',

    # Sponsoren Modul
    'dash_sponsors_eyebrow': 'Partner & Förderer',
    'dash_sponsors_title': 'Partner & Sponsoren',
    'dash_sponsors_all_link': 'Alle Sponsoren ansehen →',
    'dash_sponsors_supported_by': 'Unterstützt durch',
    'sponsors_page_title': 'Unsere Sponsoren',
    'sponsors_page_eyebrow': 'Partner & Förderer',
    'sponsors_page_subtitle': 'Ein herzliches Dankeschön an alle Partner und Unterstützer unserer LAN-Party!',
    'sponsors_visit_website': '🌐 Website besuchen →',
    'sponsors_empty': 'Aktuell sind keine Sponsoren hinterlegt.',
    'sponsors_read_more': 'Mehr anzeigen',
    'sponsors_read_less': 'Weniger anzeigen',

    # Helfer Check-in Scanner & Einlass Modul
    'scanner_title': 'Vor-Ort Einlass Check-in Scanner',
    'scanner_eyebrow': 'Einlass-Tool',
    'scanner_staff_only_badge': 'NUR FÜR MITARBEITER',
    'scanner_guests_total': 'Gäste Gesamt',
    'scanner_camera_title': 'QR-Code Scanner',
    'scanner_camera_start_btn': 'Kamera Starten',
    'scanner_result_title': 'Scan-Ergebnis',
    'scanner_guest_list_title': 'Teilnehmerliste (Manuelle Suche)',
    'scanner_cam_active': 'Kamera-Scanner aktiv...',
    'scanner_header_stats_total': 'Gäste Gesamt',
    'scanner_header_stats_paid': 'Bezahlt',
    'scanner_header_stats_checked_in': 'Eingecheckt',
    'scanner_qr_card_title': '📷 QR-Code Scanner',
    'scanner_start_camera': 'Kamera Starten',
    'scanner_camera_placeholder': 'Klicke auf "Kamera Starten" oder nutze die manuelle Suche/USB-Scanner unten.',
    'scanner_manual_code_label': 'ODER 8-STELLIGEN TICKET-CODE / TOKEN MANUELL EINGEBEN (Z. B. USB-SCANNER):',
    'scanner_btn_check': 'Prüfen',
    'scanner_result_card_title': 'Scan-Ergebnis',
    'scanner_ready_text': 'Bereit zum Scannen. Bitte QR-Code in das Kamerafeld halten oder 8-stelligen Ticket-Code eingeben.',
    'scanner_table_title': 'Teilnehmerliste (Manuelle Suche)',
    'scanner_btn_checkin': 'Einchecken',
    'scanner_btn_checkout': 'Auschecken',
    'checkin_confirm_title': 'Einlass Check-in Bestätigen',
    'checkin_guest_label': 'Gast:',
    'checkin_perform_btn': '✓ Check-in jetzt durchführen',
    'checkin_btn_confirm': '✓ Check-in jetzt durchführen',
    'checkin_success_title': 'Check-in Erfolgreich!',
    'checkin_already_done': 'Bereits Eingecheckt',
    'checkin_already_done_title': 'Bereits Eingecheckt',
    'checkin_rejected_title': 'Check-in Abgelehnt',
    'checkin_failed_title': 'Einlass fehlgeschlagen!',
    'checkin_reject_reason': 'Grund für die Ablehnung:',
    'checkin_rejection_reason_label': 'Grund für die Ablehnung:',
    'checkin_btn_back_dashboard': 'Zurück zum Dashboard',
    'back_to_dashboard': 'Zurück zum Dashboard',
}

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


def _get_active_event():
    return Event.objects.get_active()


def _get_user_registration(request):
    if not request.user.is_authenticated:
        return None
    event = _get_active_event()
    if not event:
        return None
    return (
        EventRegistration.objects.filter(event=event, user=request.user)
        .select_related('user', 'ticket_type')
        .prefetch_related('seats')
        .first()
    )


def feature_flags(request):
    """
    Schlanker Context Processor:
    Stellt Navigations-Items und Site-Customization bereit.
    upcoming_event und user_registration werden lazy über SimpleLazyObject aufgelöst (0 DB-Queries bei Seiten ohne Event-Bezug).
    """
    nav_items = cache.get_or_set(
        NAV_CACHE_KEY,
        lambda: list(
            NavigationItem.objects.filter(is_active=True).order_by(
                'order', 'id'
            )
        ),
        CACHE_SECONDS,
    )

    site_customization = SiteCustomization.load()
    css_vars = site_customization.get_css_variables()
    theme_css_inline = "\n".join([f"  {k}: {v};" for k, v in css_vars.items()])

    return {
        'nav_items': nav_items,
        'features': {},
        'feature_flags': {},
        'site_customization': site_customization,
        'theme_css_vars': theme_css_inline,
        'custom_css': site_customization.custom_css,
        'upcoming_event': SimpleLazyObject(_get_active_event),
        'user_registration': SimpleLazyObject(lambda: _get_user_registration(request)),
    }

