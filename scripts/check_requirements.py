"""Prüft, ob die installierten Pakete den exakten Pins in requirements.txt entsprechen (Befund F-001).

Aufruf: python scripts/check_requirements.py [requirements.txt]; Exitcode 1 bei Abweichungen.
"""
import re
import sys
from importlib import metadata
from pathlib import Path

PIN = re.compile(r'^\s*([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?\s*==\s*([^\s;#]+)')


def mismatches(path):
    """Liefert (Paket, gepinnte Version, installierte Version oder None) für jede Abweichung."""
    result = []
    for line in Path(path).read_text().splitlines():
        match = PIN.match(line)
        if not match:
            continue
        name, pinned = match.groups()
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed = None
        if installed != pinned:
            result.append((name, pinned, installed))
    return result


def main(argv):
    path = argv[1] if len(argv) > 1 else Path(__file__).resolve().parent.parent / 'requirements.txt'
    found = mismatches(path)
    for name, pinned, installed in found:
        print(f'{name}: erwartet {pinned}, installiert {installed or "fehlt"}')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
