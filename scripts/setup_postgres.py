#!/usr/bin/env python3
"""
Skript zur automatisierten PostgreSQL-Migration und Daten-Import aus initial_data.json.
Erstellt die Datenbank-Struktur in PostgreSQL und importiert alle bestehenden Daten verlustfrei.
"""

import os
import sys
import subprocess

def main():
    print("=== EntailsNG: PostgreSQL Migrations- & Import-Assistent ===")
    
    # Ausführen im Basisverzeichnis
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(base_dir)

    python_bin = sys.executable

    print("\n1. Erstelle Datenbank-Tabellen in PostgreSQL (`manage.py migrate`)...")
    res_migrate = subprocess.run([python_bin, "manage.py", "migrate"])
    if res_migrate.returncode != 0:
        print("\n❌ Fehler beim Erstellen der PostgreSQL-Tabellen.")
        print("Bitte stelle sicher, dass die PostgreSQL-Datenbank erreichbar ist.")
        sys.exit(1)

    print("\n2. Importiere Daten aus `initial_data.json` (`manage.py loaddata initial_data.json`)...")
    res_load = subprocess.run([python_bin, "manage.py", "loaddata", "initial_data.json"])
    if res_load.returncode != 0:
        print("\n❌ Fehler beim Importieren der Daten.")
        sys.exit(1)

    print("\n✅ Migration erfolgreich abgeschlossen!")
    print("Alle Anwendungsdaten wurden verlustfrei in die PostgreSQL-Datenbank übertragen.")

if __name__ == "__main__":
    main()
