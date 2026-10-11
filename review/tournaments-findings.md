Verifikationszusammenfassung (9. Oktober 2026): **4 BESTÄTIGT / 0 TEILWEISE ABGESICHERT / 0 FALSE POSITIVE / 0 NICHT ENTSCHEIDBAR**.

Stufe 2: Jedes Finding einzeln einschließlich URL-/Admin-Zuordnung, Roster-Decorator, Mitglieds-/Eventfilter, Models/Constraints, Signals und Templates geprüft. Geheimcode-Ausgabe im Originaltemplate mit anonymem/nichtmitgliedschaftlichem Kontext isoliert gerendert (Basislayout und URL-/Übersetzungstags gestubbt); Playoff-Sperrhelper mit gemocktem Zustand und Integerfehler ohne DB reproduziert.

Zusammenfassung: 4 Findings — Kritisch: 0, Hoch: 0, Mittel: 3, Niedrig: 1, Info: 0.

Prüfumfang: Modelle, Views einschließlich Team-/Recruitment-Aktionen, Formulare, URLs, Admin, Recruitment-Signale, Services für Anmeldung, Roster, Auslosung, Brackets, Swiss, Ergebnisse, Ranglisten, Rückzug und Neustart, externe Links, Migrationen sowie zugehörige Templates/JavaScript. Berechtigungsprüfungen, CSRF, Auto-Escaping, `json_script`, signierte Vorschauen, Versionsprüfungen und Sperrreihenfolge wurden berücksichtigt. Aktive Staff-Nutzer sind laut `Tournament.is_managed_by` ausdrücklich Turnierverwalter; dies wird nicht als fehlende Rollenprüfung gewertet. Appübergreifende Admin-Aktionsberechtigungen stehen in `_project-findings.md`.

### [TOURNAMENTS-01] Öffentliche Teamseite verrät den geheimen Einladungscode
- Schweregrad: Mittel
- Kategorie: Security
- Fundstelle: templates/tournaments/team_detail.html:164, :192, :316; tournaments/views.py:932, :987, :1139, :1199
- Beschreibung: Das sichtbare Einladungswidget liegt korrekt innerhalb von `{% if is_member %}`. Die JavaScript-Funktion darunter enthält jedoch außerhalb dieser Bedingung `team.invite_code`. `team_detail` ist öffentlich und liefert denselben Teamdatensatz auch an anonyme Besucher. Der Code wird daher im HTML-Quelltext jeder Teamseite offengelegt.
- Auswirkung / Angriffsszenario: Ein Besucher liest den Code einer fremden Teamseite aus und sendet ihn anschließend mit einem eigenen aktiven Konto und gültigem CSRF-Token an `team_join_by_code`. Bei freiem Platz wird er sofort `ACCEPTED`, ohne Einladung oder Zustimmung des Captains. Archiv-, Event-, Roster- und Kapazitätsprüfungen bleiben wirksam; betroffen sind beitretbare Teams. Der Geheimcode schützt diesen Beitritt faktisch nicht mehr.
- Betroffener Code:
  ```html
  {% endif %}
  <!-- später, außerhalb von is_member -->
  <script>
  function copyInviteCode() {
    var code = "{{ team.invite_code }}";
  }
  </script>
  ```
- Empfehlung: Den Code ausschließlich für berechtigte Mitglieder in den Response aufnehmen; die Kopierfunktion kann den Text aus dem bereits bedingt ausgegebenen Widget lesen. Offengelegte Codes rotieren. Zusätzlich Beitrittsversuche begrenzen und ausreichend lange Zufallscodes verwenden.
- Konfidenz: Hoch. Die unbedingte JavaScript-Ausgabe wurde isoliert mit der Django-Template-Engine und `is_member=False` nachvollzogen; kein tatsächlicher Teambeitritt wurde ausgeführt.

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Die Teamdetailfunktion hat keinen Login-/Mitgliederdecorator und gibt denselben Teamdatensatz an Besucher weiter. Nur das sichtbare Widget steht unter is_member; die spätere JavaScript-Variable wird innerhalb des unbedingten content-Blocks ausgegeben. Das Originaltemplate enthielt im isolierten Render bei is_member=False und anonymem Benutzer den Test-Geheimcode. Das echte Basislayout besitzt keine weitere Mitgliederbedingung. Autoescaping schützt die Syntax, nicht die Vertraulichkeit. Die Beitritts-POST-URL sucht nach genau diesem Code und erstellt ACCEPTED bzw. akzeptiert vorhandene PENDING-Mitgliedschaft.
- **Belege / Gegenmaßnahmen:** `config/urls.py:75`, `tournaments/urls.py:27`, `:28`, `tournaments/views.py:932`, `:937`, `:973`, `:987`, `:1125`, `:1139`, `:1199`, `:1208`, `templates/tournaments/team_detail.html:164`, `:192`, `:291`, `:317`, `templates/tournaments/base.html:1`, `tournaments/models.py:530`, `:552`. Login, require_POST, CSRF und Roster-Locks/-Archiv-/Eventprüfungen bleiben wirksam (`tournaments/services/rosters.py:20`, `:32`, `:52`), ebenso Spielkonflikt und Kapazität (`tournaments/views.py:1167`, `:1186`). Keiner davon verlangt die Zustimmung des Captains oder schützt den offengelegten Code; beitretbare Teams bleiben betroffen.

### [TOURNAMENTS-02] Wiederherstellung im Admin umgeht die Regeln für aktive Teammitgliedschaften
- Schweregrad: Mittel
- Kategorie: Bug
- Fundstelle: tournaments/admin.py:382; tournaments/views.py:1037, :1058; tournaments/models.py:755
- Beschreibung: Die Admin-Aktion stellt Teams durch ein direktes `queryset.update(is_archived=False)` wieder her. Sie prüft keine Konflikte der bestehenden Mitglieder mit anderen aktiven Teams desselben Spiels und verwendet nicht die Sperren bzw. Validierungen des Reaktivierungsassistenten. Die Datenbank erzwingt lediglich die Eindeutigkeit von `(team, user)`, keine Eindeutigkeit einer aktiven Spielmitgliedschaft.
- Auswirkung / Angriffsszenario: Ein Team wird archiviert; Captain oder Mitglieder treten danach einem neuen aktiven Team desselben Spiels bei. Die Admin-Wiederherstellung des alten Teams erzeugt anschließend mehrere aktive Mitgliedschaften pro Spieler/Spiel. Das widerspricht der ausdrücklich in Gründung, Beitritt und Reaktivierung durchgesetzten Regel und führt zu widersprüchlichen Team-/Anmeldedaten. Auch Mitglieder- und Eventanpassungen des Assistenten entfallen.
- Betroffener Code:
  ```python
  def action_unarchive_teams(self, request, queryset):
      count = queryset.update(is_archived=False)
  ```
- Empfehlung: Reaktivierung in einem gemeinsamen transaktionalen Service bündeln, den Admin und Frontend verwenden. Captain-/Mitgliederkonflikte, Spielgröße, Event und laufende Turniere prüfen; Konflikte sichtbar zurückmelden und keine unvalidierten Bulk-Updates erlauben.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Die registrierte TeamAdmin-Aktion setzt is_archived unmittelbar per SQL-Bulk-Update zurück. Sie ruft weder Roster-Decorator noch Reaktivierungsassistent, Model.save, full_clean oder post_save-Signals auf. Die Frontend-Reaktivierung verweigert den Captain-Spielkonflikt und entfernt Konfliktmitglieder; der Admin tut dies nicht. Die Datenbankregel betrifft nur dasselbe (team,user)-Paar und lässt verschiedene aktive Teams desselben Spiels zu. Ein normales archiviertes Team, dessen Mitglieder inzwischen anderswo spielen, kann deshalb über diesen Adminpfad widersprüchliche aktive Mitgliedschaften erzeugen.
- **Belege / Gegenmaßnahmen:** `config/urls.py:18`, `tournaments/admin.py:351`, `:356`, `:382`, `:384`, `tournaments/urls.py:29`, `tournaments/views.py:990`, `:1037`, `:1058`, `:1066`, `:1074`, `:1083`, `tournaments/models.py:593`, `:755`, `tournaments/recruitment_signals.py:29`, `tournaments/services/rosters.py:15`. Admin-Aktiv-/Staff-/Leserechte/CSRF schützen den Zugang (PROJECT-04); sie ersetzen keine fachliche Reaktivierungsprüfung. Die readonly-Felder für Teams im aktiven Turnier (`tournaments/admin.py:358`) sind Formularschutz und blockieren die Bulk-Aktion nicht. Auch eine alleinige Transaktion könnte den fehlenden Konflikttest nicht ergänzen.

### [TOURNAMENTS-03] Disqualifikation scheitert vor der Freigabe bereits besetzter Playoffs
- Schweregrad: Mittel
- Kategorie: Bug
- Fundstelle: tournaments/services/standings.py:218, :252; tournaments/services/forfeits.py:58, :78; tournaments/services/matches.py:212; tournaments/services/results.py:67, :75; tournaments/admin.py:393
- Beschreibung: Nach Abschluss der Gruppenphase werden qualifizierte Teams bereits vor der ausdrücklichen Playoff-Freigabe in `READY`-Finalspiele eingetragen. Der Rückzugsservice verarbeitet diese offenen Spiele mit `update_match_score(..., automatic_result=True)`. Auch dieser interne Aufruf durchläuft jedoch `require_editable`, das sämtliche noch nicht freigegebenen Playoffs ablehnt. Der automatische Rückzug besitzt keinen separaten zulässigen Pfad.
- Auswirkung / Angriffsszenario: Die Turnierleitung disqualifiziert ein qualifiziertes Team nach Abschluss der Gruppenspiele und vor `playoffs_released_at`. Ein besetztes Halbfinale/Finale löst `MatchAlreadyCompletedError` aus. Die umgebende Transaktion rollt den Rückzug zurück; die Admin-Aktion fängt diese Ausnahme nicht ab und liefert HTTP 500. Die gewünschte Disqualifikation bleibt aus.
- Betroffener Code:
  ```python
  TournamentMatchService.update_match_score(..., automatic_result=True)
  # auch bei automatic_result:
  require_editable(match, tournament)
  # result_lock_reason:
  if tournament.mode == Tournament.Mode.GROUP_STAGE and match.bracket_type != TournamentMatch.BracketType.GROUP and not tournament.playoffs_released_at:
      return tr('results_playoffs_unreleased')
  ```
- Empfehlung: Rückzüge vor Playoff-Freigabe als eigene Operation behandeln: Registrierung zurückziehen und die noch unfreigegebene Qualifikation unter denselben Sperren neu berechnen. Erwartbare Turnierfehler im Admin abfangen und anzeigen. Allgemeine Ergebnissperren nicht pauschal aufweichen.
- Konfidenz: Hoch für den nachvollzogenen Aufrufpfad; der komplette Datenbankablauf wurde nicht ausgeführt.

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Nach allen abgeschlossenen Gruppenspielen setzt der Standingsservice Teams in READY-Playoffs, solange die Playoffs gerade noch nicht freigegeben sind. Der erreichbare Admin-Rückzug wählt diese offenen Spiele aus und ruft update_match_score mit automatic_result=True und ohne Actor auf. Diese Kombination passiert die Actor-Grenze für automatische Ergebnisse, umgeht aber nicht den unbedingten require_editable-Aufruf. Der isolierte Original-Sperrhelper verweigerte ein vollständig besetztes PLAYED/FINAL-Match im laufenden GROUP_STAGE-Turnier mit results_playoffs_unreleased. Die erst nach Verarbeitung der offenen Matches vorgesehene Neuberechnung der Gruppenqualifikation wird nicht erreicht.
- **Belege / Gegenmaßnahmen:** `tournaments/admin.py:387`, `:393`, `tournaments/services/standings.py:202`, `:218`, `:252`, `:255`, `tournaments/services/forfeits.py:16`, `:58`, `:78`, `:96`, `tournaments/services/matches.py:195`, `:198`, `:212`, `tournaments/services/results.py:67`, `:72`, `:77`. Event-/Tournament-/Matchsperren sichern Konsistenz und Transaktionsrollback; die Aktion fängt MatchAlreadyCompletedError nicht ab. Damit bleibt der gewünschte Rückzug aus und die Adminantwort wird 500, statt teilweise falsch zu disqualifizieren. Der eigene Swiss-Rückzugspfad (`tournaments/services/forfeits.py:29`) betrifft einen anderen Modus und widerlegt das GROUP_STAGE-Szenario nicht. Kein vollständiger PostgreSQL-Turnierablauf ausgeführt.

### [TOURNAMENTS-04] Unicode-Ziffer im öffentlichen Spielfilter verursacht HTTP 500
- Schweregrad: Niedrig
- Kategorie: Bug
- Fundstelle: tournaments/views.py:783; tournaments/views.py:1026
- Beschreibung: `str.isdigit()` akzeptiert auch Zeichen wie `²`, die `int()` nicht konvertieren kann. Die Konvertierung des öffentlichen GET-Filters erfolgt ohne Ausnahmebehandlung. Dieselbe Kombination existiert für `keep_members` im Reaktivierungsformular.
- Auswirkung / Angriffsszenario: Ein anonymer Request auf die Teamliste mit `?game=%C2%B2` löst `ValueError` statt einer leeren Auswahl oder HTTP 400 aus. Ein Captain kann denselben Fehler durch `keep_members=²` auslösen. Auch extrem lange Ziffernfolgen überschreiten die Integer-Konvertierungsgrenze des verwendeten Python.
- Betroffener Code:
  ```python
  selected_game_id = int(game_filter) if game_filter.isdigit() else None
  ```
- Empfehlung: Den vorhandenen validierenden `identifier`-Helper mit Behandlung von `TournamentError` verwenden oder ein Django-Formular mit begrenztem Integer-Feld einsetzen.
- Konfidenz: Hoch. `"²".isdigit() == True` und die anschließende `ValueError` wurden lokal nachvollzogen.

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Niedrig (unverändert).**
- **Begründung:** Die öffentliche Teamliste konvertiert den freien Querystring direkt nach isdigit; es gibt kein vorgelagertes Integer-Formular. `²`.isdigit ist True, int wirft dennoch ValueError, ebenso bei einer 5000-stelligen Zahl unter der aktuellen Python-Konvertierungsgrenze. Das Roster-Wrapper-Framework serialisiert den Reaktivierungs-POST, validiert aber keep_members nicht und fängt ValueError nicht ab. Der robuste identifier-Helper wird in dieser View nur für game_id verwendet, nicht für keep_members oder den öffentlichen Filter. Der Fehler entsteht vor der Templateausgabe; dortiges Escaping hilft nicht.
- **Belege / Gegenmaßnahmen:** `tournaments/urls.py:25`, `:29`, `tournaments/views.py:775`, `:783`, `:784`, `:990`, `:1000`, `:1026`, `:1032`, `tournaments/services/rosters.py:15`, `:65`, `tournaments/services/validation.py:7`, `:20`, `configuration/middleware.py:55`. Reaktivierung erfordert Login und Captain/Staff; der Listenfilter bleibt anonym erreichbar. Die Middleware liefert/protokolliert den Serverfehler, wandelt ihn nicht in eine Validierungsantwort um.



## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |
| TOURNAMENTS-01 | bestätigt | Die Kopierfunktion liest nur das Mitglieds-Widget. 128-Bit-Codes, atomare Nutzer-/IP-Limits vor der Teamsuche und Migration 0017 zur Rotation aller offengelegten Codes. |
| TOURNAMENTS-02 | bestätigt | Admin-Wiederherstellung führt genau ein archiviertes Team in denselben transaktionalen Reaktivierungsassistenten; kein Bulk-Update mehr. Captain-/Mitgliederkonflikte, Kapazität und Event bleiben dort verbindlich. |
| TOURNAMENTS-03 | bestätigt | Noch unfreigegebene Playoffs werden beim Rückzug nicht gewertet. Der bestehende Reset-Service berechnet Qualifikanten einschließlich Freilosen neu und protokolliert Änderungen; erwartbare Turnierfehler erscheinen als Admin-Meldungen. |
| TOURNAMENTS-04 | bestätigt | Spielfilter und keep_members verwenden den begrenzten identifier-Helper. Ungültige Unicode-/überlange-/überlaufende IDs führen zu 400 bzw. Formularmeldung ohne Änderung. |

**Prüfungen:** 44 gezielte PostgreSQL-Tests (37 bestehende Auditfälle und 7 neue Regressionen) erfolgreich; vollständige Turniersuite nach der Korrektur in der erfolgreichen Gesamtsuite mit 1.293 Tests enthalten. Django-Systemcheck erfolgreich.

Deployment: Migration 0017 erneuert sämtliche Teamcodes; alte Einladungen sind danach ungültig. Die Rotation ist absichtlich nicht rückwärts ausführbar, damit öffentlich gewordene Codes nicht wiederhergestellt werden.

Die Anzeige der längeren Codes bricht in Teamkarte und Mitgliederliste responsiv um; die Kopierfunktion liest unverändert den vollständigen DOM-Text.
