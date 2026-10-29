# Sicherheitsbacklog

| ID | Status | Verantwortliche Rolle | Entscheidung und Prüfanlass |
| --- | --- | --- | --- |
| USERS-03 | Bestätigt, ausdrücklich zurückgestellt | Sicherheits-/Betriebsverantwortung | Bestehende Rechtepolitik beibehalten. Vor jeder weiteren Delegation von Benutzerverwaltung erneut prüfen; konkrete Person und Kalendertermin durch das Betreiberteam festzulegen. |
| EMAILS-F020 | Teilweise behoben, Rechtehinweis offen | Sicherheits-/Betriebsverantwortung | Inhalte von Passwort-Reset-Mails sind im Admin unter „Ausgehende E-Mails“ nicht mehr sichtbar und werden nach Versand, Ablauf oder endgültigem Fehlschlag geleert. `emails.change_generalemailsettings` bleibt faktisch superuser-äquivalent: Wer den Testmodus mit eigener Umleitungsadresse aktiviert, erhält alle Mails einschließlich Reset-Links. Dieses Recht nur Superusern geben. |

`users/admin.py` übernimmt die Rechtefelder von Djangos UserAdmin. Ein aktiver Staff mit effektivem `users.change_user` besitzt dadurch weitreichende Benutzerverwaltungsbefugnisse bis zur Änderung privilegierter Konten/Rechte. Reines `is_staff` ist dafür nicht ausreichend. Historische Entscheidung: `../review/users-findings.md`, Abschnitt USERS-03. Dieser Stand wird nicht als behoben bezeichnet.

Der folgende Bericht liest die Zielinstallation, ohne Konten, Gruppen oder Rechte zu verändern:

```bash
python manage.py audit_user_permissions --output /privater/ort/user-permissions.json
```

Das private Zielverzeichnis muss bereits existieren. Die Ausgabedatei muss neu sein und wird mit Modus 0600 erzeugt; vorhandene Dateien werden nicht überschrieben. Ohne `--output` geht JSON nach stdout. Der Bericht trennt aktive, nicht gelöschte/gesperrte Staff-Superuser von delegierten Konten mit direkter oder über Gruppen vergebener `users.change_user`-Berechtigung. Er enthält IDs/Benutzernamen und Gruppennachweise, keine E-Mail-Adressen, Passwörter oder Schlüssel. Tatsächliche Benutzerlisten privat aufbewahren, nicht ins Repository oder öffentliche CI-Artefakte übernehmen.

Bislang ist nur das Verhalten auf synthetischen Testkonten geprüft. Reale Produktionsgruppen und berechtigte Konten sind weiterhin **nicht prüfbar ohne den Bericht der Zielinstallation**. Der Betreiber ordnet die Empfänger dieser Berechtigung ausdrücklich der entsprechenden Vertrauensstufe zu.

Wenn später delegierte Profilpflege ohne Rechteverwaltung beschlossen wird, ist ein eigenes Änderungspaket erforderlich: serverseitige Feld-/Zielkontoprüfung einschließlich Gruppen, Einzelpermissions und Passwortänderung sowie Regressionen mit manipulierten POSTs. Diese bisher zurückgestellte Rechteänderung ist nicht Teil der aktuellen Umsetzung.
