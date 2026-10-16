#!/usr/bin/env python3
"""Audit an exported complete package inventory using a separate pip-audit environment.

Exit nonzero on findings, collection failures, skipped packages, or incomplete output.
No vulnerability exceptions are configured. Raw findings and tool metadata are retained.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    options = parser.parse_args()
    options.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = options.output_dir / 'dependency-audit.json'
    # Remove a stale report so a failed request cannot be mistaken for an old pass.
    report_path.unlink(missing_ok=True)
    version = subprocess.run([sys.executable, '-m', 'pip_audit', '--version'],
                             capture_output=True, text=True, check=True).stdout.strip()
    command = [
        sys.executable, '-m', 'pip_audit', '--requirement', str(options.inventory),
        '--no-deps', '--disable-pip', '--strict', '--vulnerability-service', 'pypi',
        '--format', 'json', '--aliases', 'on', '--progress-spinner', 'off',
        '--output', str(report_path),
    ]
    error = None
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        exit_code = result.returncode
        log = result.stdout + result.stderr
    except (subprocess.TimeoutExpired, OSError) as exc:
        exit_code = -1
        error = f'{type(exc).__name__}: audit did not complete'
        log = error
    (options.output_dir / 'dependency-audit.log').write_text(log)
    try:
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
    except (ValueError, OSError):
        report = {}
        error = 'Invalid or unreadable audit report'
    dependencies = report.get('dependencies', [])
    expected = sorted(line.strip().lower().replace('_', '-') for line in options.inventory.read_text().splitlines() if line.strip())
    actual = sorted(f"{dep['name']}=={dep['version']}".lower().replace('_', '-')
                    for dep in dependencies if 'version' in dep)
    complete = bool(expected) and actual == expected and all(
        'skip_reason' not in dep and isinstance(dep.get('vulns'), list) for dep in dependencies)
    # Group aliases of the same vulnerability, including cross-advisory duplicates.
    groups = []
    for dep in dependencies:
        for vuln in dep.get('vulns', []):
            ids = {vuln['id'], *vuln.get('aliases', [])}
            overlapping = [group for group in groups if group['package'] == dep['name']
                           and group['version'] == dep['version'] and ids.intersection(group['ids'])]
            for group in overlapping:
                ids.update(group['ids'])
                groups.remove(group)
            groups.append({'package': dep['name'], 'version': dep['version'], 'ids': sorted(ids)})
    summary = {
        'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'tool': version,
        'source': 'PyPI vulnerability API / Python Packaging Advisory Database',
        'inventory_sha256': hashlib.sha256(options.inventory.read_bytes()).hexdigest(),
        'exit_code': exit_code, 'error': error, 'complete': complete, 'packages': len(dependencies),
        'findings': groups, 'passed': exit_code == 0 and complete and not groups and not error,
    }
    (options.output_dir / 'audit-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))
    raise SystemExit(0 if summary['passed'] else 1)


if __name__ == '__main__':
    main()
