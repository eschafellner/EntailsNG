#!/usr/bin/env python3
"""Check the installed Django security baseline and export the actual package set."""
import argparse
from importlib import metadata
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent


def inventory():
    import django

    # requirements.txt ist ein pip-compile-Lockfile: "django==6.0.9 \\" mit folgenden --hash-Zeilen.
    match = re.search(r'^django==([0-9.]+)\s*\\?\s*$', (ROOT / 'requirements.txt').read_text(), re.MULTILINE | re.IGNORECASE)
    if not match:
        raise RuntimeError('An exact Django pin is required in requirements.txt.')
    expected = match.group(1)
    if django.get_version() != expected or django.VERSION[:2] != (6, 0) or django.VERSION[:3] < (6, 0, 9):
        raise RuntimeError(f'Django security baseline mismatch: expected {expected} (6.0.9+), got {django.get_version()}.')
    # Some platforms expose the same site-packages through lib and lib64.
    installed = {}
    for dist in metadata.distributions():
        name = dist.metadata['Name']
        canonical = re.sub(r'[-_.]+', '-', name).lower()
        if canonical in installed and installed[canonical]['version'] != dist.version:
            raise RuntimeError(f'Conflicting installed versions of {name}.')
        installed[canonical] = {'name': name, 'version': dist.version}
    packages = [installed[name] for name in sorted(installed)]
    return {'python': sys.version.split()[0], 'django': django.get_version(),
            'expected_django': expected, 'packages': packages}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    options = parser.parse_args()
    result = inventory()
    if options.output_dir:
        options.output_dir.mkdir(parents=True, exist_ok=True)
        (options.output_dir / 'runtime.json').write_text(json.dumps(result, indent=2) + '\n')
        (options.output_dir / 'runtime-requirements.txt').write_text(''.join(
            f"{package['name']}=={package['version']}\n" for package in result['packages']))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
