Verifikationszusammenfassung (9. Oktober 2026): **4 BESTÄTIGT / 0 TEILWEISE ABGESICHERT / 0 FALSE POSITIVE / 0 NICHT ENTSCHEIDBAR**.

Stufe 2: Alle vier Pfade einschließlich URL-Mapping, Middleware, Formularen, Model-Schutz und Templates geprüft. Tatsächlich delegierte Produktionsrechte sind unbekannt; die entsprechende Voraussetzung bleibt ausdrücklich Teil von USERS-03.

Zusammenfassung: 4 Findings — Kritisch: 0, Hoch: 1, Mittel: 2, Niedrig: 1, Info: 0.

Geprüft: Modelle, Auth-Backend, Formulare, Views/URLs, Account-/Moderationsservices, Tokens, Admin, Migrationen, Auth-/Profil-/Admin-Templates sowie einschlägige vorhandene Tests. Keine Serializer vorhanden. CSRF-Middleware, explizite Profilfelder, kryptografische Codes, fünf Codefehlversuche und Datenbanksperren wurden berücksichtigt.

### [USERS-01] Aktivierungsanfrage verrät die E-Mail-Adresse hinter einem Benutzernamen
- Schweregrad: Mittel
- Kategorie: Security
- Fundstelle: users/views.py:229, :240, :247, :176; templates/auth/verify_email.html:62
- Beschreibung: Der öffentliche Aktivierungsendpunkt sucht auch nach Benutzernamen. Bei einem unbestätigten Konto mit vorhandenem Code setzt er ohne Passwortprüfung dessen ID in die Session und leitet zur Verifikation weiter, auch beim Cooldown. Die Verifikationsseite zeigt anschließend die vollständige E-Mail-Adresse. Der angekündigte Enumerationsschutz greift für diesen Pfad nicht.
- Auswirkung / Angriffsszenario: Ein anonymer Besucher gibt den Benutzernamen eines unbestätigten Kontos an und liest dessen private E-Mail-Adresse auf `/verify-email/`. Das unterschiedliche Redirect-Verhalten verrät außerdem den Kontostatus. Der Code selbst wird nicht ausgegeben; dies ist keine unmittelbare Kontoübernahme.
- Betroffener Code:
  ```python
  user = User.objects.filter(username__iexact=email_input, is_active=False,
      deleted_at__isnull=True, is_banned=False).first()
  request.session['pending_verification_user_id'] = user.id
  return redirect("verify_email")
  ```
- Empfehlung: Wiederaufnahme erst nach Passwortprüfung erlauben oder bei öffentlichen Anfragen ein neutrales Ergebnis liefern und die tatsächliche Adresse nicht ausgeben. Maskierung alleine muss ausreichend sein, um keinen neuen Adressanteil preiszugeben.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** `/request-activation-code/` ist öffentlich. Der POST liest einen freien Textwert ohne Passwortprüfung und setzt bei vorhandenen Registrierungscodes auch im Cooldown die Verifikationssession. Der anschließende öffentliche GET benötigt nur diese selbst erzeugte Session und liefert `user.email`. Template-Autoescaping verhindert HTML-Injektion, verbirgt aber keine Adresse. Neutraler Text im anderen Antwortzweig vereinheitlicht weder Redirect noch Zielseite.
- **Belege / Gegenmaßnahmen:** `config/urls.py:21`, `users/urls.py:6`, `:8`, `users/views.py:207`, `:233`, `:236`, `:240`, `:247`, `:83`, `:92`, `:176`, `templates/auth/verify_email.html:62`. CSRF (`config/settings.py:102`, `templates/auth/request_activation.html:32`) und IP-Limit (`users/views.py:215`) hindern einen Besucher nicht daran, eigene gültige Anfragen zu stellen. Benutzer-/Codesperren und fünf Codeversuche (`users/models.py:317`, `:374`) sichern die Aktivierung, nicht die Adressausgabe. Gesperrte/gelöschte sowie bereits aktive Konten sind vom beschriebenen Leck ausgeschlossen.

### [USERS-02] Passwortfehlversuche für inaktive Konten werden nicht gezählt
- Schweregrad: Mittel
- Kategorie: Security
- Fundstelle: users/auth_backends.py:145, :184
- Beschreibung: Der Inaktiv-Pfad prüft das Passwort und gibt danach unmittelbar `None` zurück. Er ruft weder `_record_ip_failed_attempt` noch `register_failed_login` auf und prüft auch keine Kontosperre. Die Zähler werden ausschließlich im späteren Aktiv-Pfad erhöht.
- Auswirkung / Angriffsszenario: Ein Angreifer kann für ein unbestätigtes Konto unbegrenzt Passwörter versuchen; ein Treffer ist an der besonderen Formularmeldung und Verifikationssession erkennbar (`users/forms.py:218`). Sobald der Besitzer das Konto bestätigt, ist das ermittelte Passwort für den Login nutzbar. Vorher schützt weiterhin die E-Mail-Verifikation vor direktem Login.
- Betroffener Code:
  ```python
  if not user.is_active:
      if user.check_password(password):
          ...
          setattr(request, 'unverified_user', user)
      return None
  ```
- Empfehlung: Passwortfehlversuche unabhängig vom Aktivierungsstatus atomar zählen und Sperren vor der Passwortprüfung anwenden; Wiederaufnahme nur innerhalb derselben Limits ermöglichen.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** `/login/` verwendet ausdrücklich `CustomAuthenticationForm` und ausschließlich dieses Backend. Für einen nicht gesperrten, nicht gelöschten inaktiven Benutzer wird das Passwort geprüft und anschließend vor sämtlichen Account-Zähler-/Lockout-Aufrufen zurückgekehrt. Bei einem Treffer und noch unbenutztem Registrierungscode erzeugt das Formular eine erkennbare Meldung samt Verifikationssession. Der vorgeschaltete IP-Limit-Check existiert, zählt aber diese Fehlversuche selbst nicht: Ohne anderswo aufgefüllten Zähler begrenzt er diesen Angriff nicht.
- **Belege / Gegenmaßnahmen:** `config/urls.py:23`, `config/settings.py:273`, `users/forms.py:204`, `:218`, `users/auth_backends.py:117`, `:142`, `:146`, `:154`, `:156`, `:184`. Passwort-Hashvergleich und E-Mail-Codeprüfung bleiben wirksam (`users/auth_backends.py:147`, `users/models.py:401`); CSRF schützt den Login-POST, nicht vor eigenen Passwortversuchen. Der Erfolg ist nicht bei jedem beliebigen administrativ deaktivierten Konto erkennbar, sondern bei vorhandener offener Verifikation, wie im Angriffsszenario vorausgesetzt.

### [USERS-03] Delegierte Benutzerverwaltung erlaubt die Vergabe von Superuserrechten
- Schweregrad: Hoch
- Kategorie: Security
- Fundstelle: users/admin.py:16, :34, :53, :61
- Beschreibung: `CustomUserAdmin` übernimmt die Berechtigungsfelder des Django-`UserAdmin` (`is_superuser`, `is_staff`, `groups`, `user_permissions`) und dessen generische Änderungsberechtigung. Die eigenen Einschränkungen betreffen nur gelöschte/gesperrte Konten. Für einen aktiven Staff mit `users.change_user` gibt es keine Begrenzung nach Zielkonto oder Superuserstatus des Bearbeiters.
- Auswirkung / Angriffsszenario: Ein Mitarbeiter, dem Benutzerpflege delegiert wurde, kann sein eigenes `is_superuser` setzen oder ein bestehendes Superuserkonto bearbeiten. Voraussetzung ist ausdrücklich `users.change_user`; bloßer Staffstatus genügt nicht. Django schützt den Admin-Zugang, begrenzt diese Felder aber nicht automatisch. Wenn diese Permission bewusst ausschließlich voll vertrauenswürdigen Administratoren vorbehalten ist, besteht keine zusätzliche Grenze zum Überschreiten; die tatsächliche Gruppenzuweisung im Betrieb wurde nicht geprüft.
- Betroffener Code:
  ```python
  class CustomUserAdmin(UserAdmin):
      fieldsets = UserAdmin.fieldsets + (...)
      def has_change_permission(self, request, obj=None):
          if obj and obj.deleted_at:
              return False
          return super().has_change_permission(request, obj)
  ```
- Empfehlung: Rechtefelder und privilegierte Zielkonten serverseitig auf Superuser beschränken, einschließlich Hinzufügen, Passwortänderung und M2M-Permissions; alternativ Benutzerpflege explizit als Superuseräquivalent behandeln und die Permission entsprechend restriktiv vergeben.
- Konfidenz: Mittel (Codepfad eindeutig, Ausnutzbarkeit hängt von delegierten Permissions ab)

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Hoch (unverändert, bedingt durch delegiertes `users.change_user`).**
- **Begründung:** Der registrierte Admin übernimmt `UserAdmin.fieldsets` samt Rechtefeldern. Seine Änderungsprüfung verweigert nur gelöschte Ziele und delegiert ansonsten an die Modellpermission. Weder Model-Clean noch Model-Save vergleichen den Bearbeiter mit einem Superuser; die Save-Sperre schützt Löschung/Ban-Zustand, lässt `is_superuser` jedoch unverändert durch. Ein aktiver Staff mit `users.change_user` kann deshalb sein eigenes aktives Konto bearbeiten. Django behandelt dieses Recht bei User-Verwaltung als hochprivilegiert; das ist keine automatische Feldbegrenzung.
- **Belege / Gegenmaßnahmen:** `config/urls.py:18`, `users/admin.py:16`, `:34`, `:53`, `:61`, `users/models.py:88`, `:100`, `:124`; geerbte Rechtefelder `/tmp/breakpoint-review-20261007/lib/python3.14/site-packages/django/contrib/auth/admin.py:44`, `:53`; generische Prüfung `/tmp/breakpoint-review-20261007/lib/python3.14/site-packages/django/contrib/admin/options.py:569` in derselben Prüfumgebung (Django 6.0.9). Admin-Aktiv-/Staffprüfung und CSRF schützen den Zugang, begrenzen autorisierte Rechteänderungen aber nicht (Framework-Abgleich siehe PROJECT-04). Der eigene Moderationspfad verlangt zusätzliche Rechte (`users/admin.py:78`), der normale Change-Pfad durchläuft ihn nicht. Die reine Add-Seite bietet standardmäßig keine Superuserfelder; die Änderung eines bestehenden Kontos genügt. Aus der fehlenden Kenntnis realer Gruppenzuweisungen folgt kein False Positive für diesen ausdrücklich bedingten Codebefund.

### [USERS-04] Passwort-Reset-Limits verwenden nichtatomare Zähler
- Schweregrad: Niedrig
- Kategorie: Security
- Fundstelle: users/forms.py:249, :256, :261, :268; users/views.py:215, :225
- Beschreibung: Passwort-Reset und Aktivierungsanfrage lesen Zähler mit `cache.get` und schreiben später `count + 1`. Gleichzeitige Requests können denselben Wert lesen und einander überschreiben. Anders als Login-/Codeprüfungen verwenden diese Pfade keine atomare Inkrementierung.
- Auswirkung / Angriffsszenario: Parallele Passwort-Reset-Anfragen an dieselbe Adresse können mehr als drei E-Mails pro Stunde auslösen, während der Zähler nur um eins steigt. Bei Aktivierungen begrenzt der DB-basierte Code-Cooldown den tatsächlichen Versand zusätzlich; beim Passwort-Reset fehlt diese zweite Sperre.
- Betroffener Code:
  ```python
  email_count = cache.get(email_key, 0)
  if email_count >= 3:
      return
  cache.set(email_key, email_count + 1, 3600)
  ```
- Empfehlung: Zähler atomar reservieren, z. B. Redis-Skript für Inkrement und TTL, und beide Limits vor dem Versand verbindlich durchsetzen.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Niedrig (unverändert).**
- **Begründung:** Der erreichbare Django-PasswordResetView übergibt an das eigene Formular; dieses macht für beide Schlüssel getrennte Get-/Set-Aufrufe und erstellt danach die Mail. Auch mit Redis ist nur jeder einzelne Cacheaufruf atomar, nicht das Lesen-Prüfen-Schreiben. Parallele eigene CSRF-gültige Sitzungen können denselben alten Stand lesen. Für Reset-Mails existiert hier weder DB-Cooldown noch deduplizierender Token-/Outbox-Constraint. Beim Aktivierungscode ist das gleiche Cachemuster vorhanden, jedoch begrenzt die Benutzersperre mit zentralem Cooldown den tatsächlichen Versand zusätzlich; diese Einschränkung ist im Original bereits korrekt genannt.
- **Belege / Gegenmaßnahmen:** `config/urls.py:37`, `users/forms.py:238`, `:250`, `:256`, `:262`, `:268`, `:275`, `:289`, `config/settings.py:178`, `users/views.py:216`, `:225`, `users/services.py:73`, `users/models.py:314`, `:327`. Aktive/nicht gesperrte Zielkonten und kryptografischer Reset-Token begrenzen die Auswirkungen auf Mail-/Queue-Spam, nicht Kontoübernahme. Login- und Verifikationszähler (`users/auth_backends.py:83`, `users/views.py:107`) schützen andere Endpunkte und werden vom Reset-Pfad nicht aufgerufen.



## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |
| USERS-01 | bestätigt | Öffentliche Aktivierungsanfragen liefern unabhängig von Konto/Cooldown dieselbe Meldung und Weiterleitung. Keine Verifikationssession ohne Passwortnachweis; Wiederaufnahme über Login bleibt möglich. |
| USERS-02 | bestätigt | Kontosperren gelten vor jeder Passwortprüfung; auch inaktive Konten erhöhen bei Fehlversuchen atomar Konto- und IP-Zähler. Richtige Passwörter können innerhalb der Limits weiterhin zur Verifikation führen. |
| USERS-03 | bestätigt | Codepfad bestätigt. Auf ausdrücklichen Wunsch des Nutzers vorerst zurückgestellt; Rechtepolitik bleibt unverändert. |
| USERS-04 | bestätigt | Reset-/Aktivierungslimits reservieren atomar vor dem Versand; Redis INCR+TTL per Lua, LocMem add/incr mit begrenztem Retry bei Ablauf. Cachefehler erlauben keinen Versand. |

**Prüfungen:** 67 Benutzertests erfolgreich auf isoliertem PostgreSQL, inklusive 5 neuer Regressionstests für neutrale Antworten, Lockout inaktiver Konten und 80 parallele Limitreservierungen. Bestehender Aktivierungstest an sichere Antwort angepasst.

**Zurückgestellt:** USERS-03 bleibt auf Wunsch des Nutzers vorerst außen vor. Die Modulprüfung ist abgeschlossen; an der delegierten Rechtegrenze und an Produktionsgruppen wurde nichts geändert.
