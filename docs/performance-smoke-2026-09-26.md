# Lokaler Performance-Smoke-Test (26. September 2026)

Die Messung lief auf einer eigens angelegten PostgreSQL-Wegwerf-Datenbank.
`scripts/performance_smoke.py` erzeugt pro Szenario ein offenes Testevent und
50, 250 oder 1.000 Konten. Zwölf Threads melden diese Gäste über
`RegistrationService` an. Die Scannerzeit stammt aus drei warmen Django
Test-Client-Aufrufen; angegeben ist der Median. `DEBUG=True` und ein lokaler
Cache waren aktiv. Die Werte sind Vergleichswerte auf diesem Rechner und
keine Produktionslatenzen.

| Gäste | Anmeldung p95 vorher / nachher | Scanner vorher / nachher | HTML vorher / nachher |
| ---: | ---: | ---: | ---: |
| 50 | 23,46 / 25,16 ms | 20,57 / 6,85 ms | 98 / 67 kB |
| 250 | 20,39 / 21,21 ms | 81,22 / 6,78 ms | 416 / 67 kB |
| 1.000 | 18,92 / 18,95 ms | 388,78 / 7,55 ms | 1.612 / 67 kB |

Der Scanner lädt jetzt 30 Einträge pro Anfrage. Suche und Statusfilter laufen
serverseitig. Ein zusätzlicher Browserdurchlauf hat das Nachladen von 30 auf
60 Zeilen und die Suche nach dem letzten von 1.000 Gästen bestätigt.

Ein separater Durchlauf mit 1.000 Gästen und **32 parallelen Threads** ergab
52,9 ms p95, 0 Fehler und bis zu 31 PostgreSQL-Sessions, die gleichzeitig auf
eine Sperre warteten. Das Event-Zeilenschloss serialisiert die Anmeldung
bewusst, um Überbuchung und Änderungen am Eventzustand korrekt abzufangen.
Bei der getesteten Last war die Antwortzeit noch niedrig. Bei deutlich mehr
Web-Workern oder höherer Last sollte man die Sperrwartezeit erneut messen.

Die bisherige PDF-Erzeugung hat bei 1.000 A4-Urkunden das 60-Sekunden-Limit
eines Gunicorn-Workers überschritten und wurde abgebrochen. Sie las für jede
weitere Seite das bisherige PDF erneut ein. Der neue fortlaufende PDF-Writer
benötigte für dieselbe Stichprobe **10,92 s** und erzeugte rund **160 MB**.
Die PDF-Struktur wurde mit `pdfinfo` sowie den PDF-Tests geprüft. Reale
Hintergrundbilder, Hardware und parallele Exporte können die Dauer erhöhen;
für sehr große oder häufige Exporte bleibt ein Hintergrundauftrag sinnvoll.

Zum Wiederholen eine *ausschließlich dafür angelegte* PostgreSQL-Datenbank
verwenden und `ENTAILS_PERF_TEST=1` setzen. Das Skript prüft beide Bedingungen
und lässt andere Datenbanken unberührt, legt aber bei jedem Lauf neue Testdaten
in der Perf-Datenbank an. Beispiel:

```sh
ENTAILS_PERF_TEST=1 REDIS_URL= DB_NAME=entails_perf_db \
DB_USER=entails_test DB_HOST=/tmp DB_PORT=55432 DEBUG=True \
.venv/bin/python scripts/performance_smoke.py --label nachher
```

Für die Sperrmessung `--sizes 1000 --workers 32 --sample-locks` ergänzen.
