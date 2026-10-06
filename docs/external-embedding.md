# Externe Seiten und Bildergalerien einbetten

Inhaltsseiten unterstützen den Seitentyp **Externe Einbettung**. Beim Aufruf
lädt das iframe direkt; es gibt keinen zusätzlichen Ladebutton. Menü,
Seitenkopf und Infoseiten-Tabs bleiben erhalten. Bestehende Seiten werden durch
die Migration als Textseiten übernommen.

## Einrichtung

1. `python manage.py migrate` ausführen (Migration `info.0004_external_embedding`).
2. `python manage.py seed_translations` und `python manage.py collectstatic --noinput`
   ausführen, Webprozesse neu starten.
3. Im Admin unter **Info → Einbettungsanbieter** einen Anbieter anlegen, z. B.
   „Bildergalerie“ mit `https://galerie.example.com`. Nur Schema, Host und optional
   Port eintragen: keinen Pfad, abschließenden Slash oder Parameter.
4. Unter **Inhaltsseiten / Infoseiten** eine Seite anlegen, Titel und Slug setzen
   und **Externe Einbettung** auswählen. Anbieter und vollständige HTTPS-Adresse
   eintragen. Ein Einführungstext ist optional.
5. Für PicGallery das Profil **Interaktive Galerie** wählen. Es erlaubt
   JavaScript, den Speicherzugriff der Galerie, Bilddownloads und Vollbild.
   Das statische Profil erlaubt kein JavaScript, keine Downloads oder Vollbild.
6. Rahmenhöhe (320–2000 Pixel, Standard 800) und breite/Standardansicht wählen.
   Veröffentlichung, Hauptnavigation, Icon und Reihenfolge wie gewohnt setzen.
   Mit Slug `bildergalerie` ist die Seite unter `/info/bildergalerie/` erreichbar.

Anlegen/Ändern von Anbietern setzt die Django-Adminrechte für `info.EmbedProvider`
voraus. Diese Rechte nur vertrauenswürdigen Administratoren erteilen: Eine
Freigabe erlaubt diesem Anbieter externe Inhalte auszuliefern.

## Freigabe auf dem Galerie-Server

Geprüfter PicGallery-Stand: `eschafellner/picgallery2.0`, Commit
`85d6f081140e910a209ba602388e30ce39f646cd`. In
`picture-gallery-server/src/app.ts` setzt der Server `X-Frame-Options: SAMEORIGIN`.
Dadurch wird eine Einbettung von einer anderen Origin blockiert, auch von einer
Subdomain oder einem anderen Port.

Auf dem Galerie-Server diesen Header durch eine gezielte Freigabe ersetzen:

```http
Content-Security-Policy: frame-ancestors 'self' https://entails.example.com;
```

Die Beispieladresse durch die tatsächliche **Entails-NG-Origin** ersetzen.
Bei bereits vorhandener CSP deren Direktiven beibehalten und `frame-ancestors`
gezielt ändern. Die Freigabe muss auf der HTML-Antwort der Galerie wirksam sein.

Alternativ am vorgeschalteten Galerie-Reverse-Proxy konfigurieren. Nginx:

```nginx
# Im bestehenden location-Block der Galerie:
proxy_hide_header X-Frame-Options;
add_header Content-Security-Policy "frame-ancestors 'self' https://entails.example.com" always;
```

Caddy:

```caddyfile
# Im bestehenden reverse_proxy-Block der Galerie:
header_down -X-Frame-Options
header_down Content-Security-Policy "frame-ancestors 'self' https://entails.example.com"
```

Die Proxybeispiele setzen voraus, dass noch keine weitere CSP existiert. Ein
global vom Proxy ergänzter Frame-Header oder eine weitere CSP muss ebenfalls
an der endgültigen Antwort geprüft werden. `CORS_ORIGIN` ist keine iframe-Freigabe.
Die Galerie ruft ihre API im iframe auf ihrer eigenen Origin auf. Entails-NGs
eigenes `X_FRAME_OPTIONS = 'DENY'` bleibt bestehen: Es schützt Entails-NG vor
Einbettung auf anderen Seiten.

Die Serveradresse und Hostingkonfiguration wurden nicht mitgeliefert. Deshalb
wurde der externe Galerie-Server nicht verändert und kein erfolgreicher Test
der tatsächlichen gehosteten Galerie behauptet.

## Verhalten und Grenzen

- Nur HTTPS-Adressen auf der exakt freigegebenen Anbieter-Origin sind erlaubt;
  Zugangsdaten, unsichere Schemata, Steuerzeichen und fremde Hosts werden abgewiesen.
- Die Seite setzt CSP `frame-src` auf die Anbieter-Origin. Umleitungen auf
  andere Origins können blockiert werden. Das Galerieprofil erlaubt weder
  Popups noch Navigation der Entails-NG-Seite oder Formularübermittlung.
- Einbettungen auf Entails-NGs eigener Origin werden nicht gerendert, um die
  Kombination aus JavaScript und `allow-same-origin` sicher zu halten.
- Deaktivieren des Anbieters entfernt iframe und externen Link bei nachfolgenden
  Seitenaufrufen. Bereits offene Frames werden nicht nachträglich geschlossen.
  Anbieter mit verknüpften Seiten sind vor Löschung geschützt.
- „Nur für angemeldete Benutzer“ schützt die interne Seiten-URL und blendet
  ihren automatisch verwalteten Menüpunkt für Gäste aus. Die externe Galerie
  benötigt für vertrauliche Inhalte einen eigenen Zugriffsschutz. Vorgeschaltete
  Anmeldungen und eingeschränkter Drittanbieter-Speicher erfordern Browserprüfungen.
- Ein dauerhaft sichtbarer Link öffnet die externe Seite separat. Browser melden
  iframe-Ladefehler nicht zuverlässig; deshalb gibt es keine automatische
  Erfolgserkennung oder versprochene automatische Fehlermeldung.
- Breite passt sich an das Gerät an. Höhe ist fest einstellbar; Lightboxen liegen
  innerhalb des Frames. Vollbild erfordert Browserunterstützung und einen Klick.
  Automatische Inhaltshöhe würde eine abgestimmte `postMessage`-Schnittstelle
  beim Anbieter voraussetzen.
- Die Kernanwendung bleibt lokal nutzbar; externe Inhalte benötigen Zugang zum
  Galerie-Server. PicGallery lädt aktuell Google Fonts. Für vollständigen
  LAN-Betrieb Galerie und Fonts lokal bereitstellen. Sandbox und Referrer-Policy
  verhindern nicht alle Drittanbieteranfragen innerhalb der Galerie.
- Der allgemeine HTML-Sanitizer entfernt weiterhin frei eingetragene iframes.
  Einbettungen entstehen ausschließlich aus den strukturierten Seitenfeldern.

## Prüfung

Am 6. Oktober 2026: 102 Info-/Konfigurationstests gegen PostgreSQL und 24
JavaScript-Tests erfolgreich; Systemcheck, Syntax und Migrationsabgleich ohne
Fehler. Desktop, 390-Pixel-Mobilansicht ohne horizontalen Überlauf, direkte
iframe-Ladung, JavaScript-/Speicherinteraktion und Admin-Seitentypwechsel geprüft.
Lokal `info.0003` (vorher noch offen) und `info.0004` angewendet, Übersetzungen
ergänzt und statische Dateien gesammelt. Die temporäre Vorschau ist getrennt
von der lokalen Projektdatenbank.

`python manage.py test info configuration --noinput` prüft Textseiten,
Admin-Formulare, Anbieter-/URL-Validierung, unmittelbare Einbettung, Sandbox,
CSP, Login-Schutz, Entwürfe, Navigation sowie die Deaktivierung von Anbietern.
Die visuelle Prüfung verwendet eine isolierte PostgreSQL-Vorschau und eine
lokale HTTP-Testgalerie (ausschließlich in der Testausgabe umgeschrieben);
Produktvalidierung und Tests verlangen weiterhin HTTPS. Für den konkreten
Galerieanbieter nach Einrichtung zusätzlich Albenwechsel, Theme, Lightbox,
Download, Vollbild und Anmeldung in Desktop- und Mobilbrowsern prüfen.
