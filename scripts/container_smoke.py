#!/usr/bin/env python3
"""Build/run an isolated copy with unique resources; never use the checkout's .env or volumes."""
import argparse
import base64
import http.client
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
import ssl

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--performance', action='store_true', help='Also record HTTP performance baseline on disposable data.')
    parser.add_argument('--tests', action='store_true', help='Run the full Django suite inside the isolated Python 3.12 image.')
    parser.add_argument('--test-processes', type=int, choices=range(1, 5), default=1,
                        help='Number of isolated Django test processes (default: 1).')
    options = parser.parse_args()
    output = Path(options.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    name = 'entails-smoke-' + secrets.token_hex(6)
    secret_values = [secrets.token_urlsafe(50) for _ in range(4)]

    def redact(text):
        for value in secret_values:
            text = text.replace(value, '[redacted]')
        return text

    def run(args, *, check=True, timeout=600):
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError(redact((result.stdout + result.stderr)[-5000:]))
        return result

    with tempfile.TemporaryDirectory(prefix=name + '-') as temporary:
        stage = Path(temporary)
        # Git's ignore rules exclude .env, media, private keys, local DBs and caches.
        paths = run(['git', '-C', str(ROOT), 'ls-files', '--cached', '--others', '--exclude-standard', '-z']).stdout.split('\0')
        for relative in paths:
            if (not relative or relative.startswith(('.aws/', '.codex/', '.agents/', 'media/', 'private_media/', 'backups_data/', 'data/certbot/'))
                    or (Path(relative).name.startswith('.env') and Path(relative).name != '.env.example')):
                continue
            source = ROOT / relative
            if source.is_file() and not source.is_symlink():
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        environment = {
            'SECRET_KEY': secret_values[0], 'FIELD_ENCRYPTION_KEY': secret_values[1],
            'USER_BAN_HMAC_KEY': secret_values[2], 'DB_PASSWORD': secret_values[3],
            'DB_NAME': 'entails_smoke_container', 'DB_USER': 'entails_smoke', 'DB_HOST': 'db',
            'DEBUG': 'False', 'ALLOWED_HOSTS': 'localhost,127.0.0.1',
            'DOMAIN_NAME': 'localhost', 'HTTP_PORT': '0', 'HTTPS_PORT': '0',
            'PUBLIC_BASE_URL': 'https://localhost', 'REDIS_PASSWORD': secrets.token_urlsafe(32),
            'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
            'DEMO_MODE': 'False', 'CLOUDFLARE_TUNNEL_TOKEN': '', 'CERTBOT_EMAIL': 'smoke@example.invalid',
            'BACKUP_ENCRYPTION_KEY': base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        }
        secret_values.extend([environment['BACKUP_ENCRYPTION_KEY'], environment['REDIS_PASSWORD']])
        (stage / '.env').write_text(''.join(f'{key}={value}\n' for key, value in environment.items()))
        (stage / '.env').chmod(0o600)
        initial = ['docker', 'compose', '--project-directory', str(stage), '-f', str(stage / 'docker-compose.yml'), '--env-file', str(stage / '.env'), '--profile', 'backups']
        # Discard ambient Compose interpolation variables; use only our generated environment.
        interpolation = {**os.environ, **environment}
        rendered = subprocess.run([*initial, 'config', '--format', 'json'], env=interpolation,
                                  text=True, capture_output=True, check=True)
        config = json.loads(rendered.stdout)
        config['name'] = name
        image = name + '-app:smoke'
        for service_name in ('certbot', 'cloudflared'):
            config['services'].pop(service_name, None)
        for volume in ('smoke_certificates', 'smoke_acme'):
            config['volumes'][volume] = {'name': f'{name}_{volume}'}
        for service_name, service in config['services'].items():
            service.pop('container_name', None)
            service.pop('profiles', None)
            service.pop('ports', None)
            for mount in service.get('volumes', []):
                if mount['target'] in ('/etc/letsencrypt', '/var/www/certbot'):
                    mount['type'] = 'volume'
                    mount['source'] = 'smoke_certificates' if mount['target'] == '/etc/letsencrypt' else 'smoke_acme'
                    mount.pop('bind', None)
                elif mount['type'] == 'bind':
                    # Relabel only the isolated copied files on SELinux hosts.
                    mount.setdefault('bind', {})['selinux'] = 'Z'
            if 'build' in service:
                service['image'] = image
                if service_name != 'web':
                    del service['build']
        config['services']['nginx']['ports'] = [
            {'target': 443, 'published': '0', 'host_ip': '127.0.0.1', 'protocol': 'tcp'}]
        # Compose config materializes the original project prefix; replace every volume name.
        for volume_name, volume in config['volumes'].items():
            volume['name'] = f'{name}_{volume_name}'
        for network_name, network in config.get('networks', {}).items():
            network['name'] = f'{name}_{network_name}'
        composed = stage / 'smoke-compose.json'
        composed.write_text(json.dumps(config))
        composed.chmod(0o600)
        compose = ['docker', 'compose', '-p', name, '--project-directory', str(stage), '-f', str(composed)]
        started = False
        try:
            print('Building isolated application image...', flush=True)
            result = run([*compose, 'build', 'web'], check=False, timeout=1800)
            (output / 'build.log').write_text(redact(result.stdout + result.stderr))
            if result.returncode:
                raise RuntimeError('Imagebuild fehlgeschlagen; siehe bereinigtes build.log.')
            started = True
            run([*compose, 'up', '-d', '--wait', '--wait-timeout', '240'], timeout=300)
            versions = {}
            image_id = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image]).stdout.strip()
            for service in ('web', 'email_worker', 'clan_seat_worker', 'guest_photo_worker', 'backup_worker'):
                probe = run([*compose, 'exec', '-T', service, 'python', 'scripts/dependency_inventory.py'])
                versions[service] = json.loads(probe.stdout)
                container_id = run([*compose, 'ps', '-q', service]).stdout.strip()
                actual_image = run(['docker', 'inspect', '--format', '{{.Image}}', container_id]).stdout.strip()
                assert actual_image == image_id, f'{service} is not running the tested image'
                run([*compose, 'exec', '-T', service, 'python', '-m', 'pip', 'check'])
            (output / 'service-versions.json').write_text(json.dumps(
                {'image_id': image_id, 'services': versions}, indent=2) + '\n')
            runtime = versions['web']
            (output / 'runtime.json').write_text(json.dumps(runtime, indent=2) + '\n')
            (output / 'runtime-requirements.txt').write_text(''.join(
                f"{package['name']}=={package['version']}\n" for package in runtime['packages']))
            deploy = run([*compose, 'exec', '-T', 'web', 'python', 'manage.py', 'check',
                          '--deploy', '--fail-level', 'WARNING'], check=False)
            (output / 'deployment-check.log').write_text(redact(deploy.stdout + deploy.stderr))
            if deploy.returncode:
                raise RuntimeError('Deploymentcheck fehlgeschlagen; siehe deployment-check.log.')
            labels = [] if options.tests else ['config.test_header_parsing', 'config.test_dependency_checks']
            print('Running Django tests inside the isolated image (full suite)...' if options.tests
                  else 'Running header and dependency security gates inside the isolated image...', flush=True)
            suite = run([*compose, 'exec', '-T', '-e', 'SECURE_SSL_REDIRECT=False',
                         '-e', 'DJANGO_LOG_LEVEL=WARNING', 'web', 'python', 'manage.py',
                         'test', '--noinput', '--parallel', str(options.test_processes), *labels],
                        check=False, timeout=1800)
            (output / 'django-tests.log').write_text(redact(suite.stdout + suite.stderr))
            if suite.returncode:
                raise RuntimeError('Django-Tests fehlgeschlagen; siehe django-tests.log.')
            run([*compose, 'exec', '-T', 'web', 'python', 'manage.py', 'check_runtime',
                 '--health-host', '127.0.0.1', '--require-redis'])
            run([*compose, 'exec', '-T', '-e', 'ENTAILS_SETUP_SMOKE=1', 'web',
                 'python', 'scripts/redis_smoke.py'])
            negative = {}
            for variable, value, expected in (('REDIS_URL', 'redis://127.0.0.1:1/1', 'cache'),
                                               ('DB_PORT', '1', 'database')):
                probe = run([*compose, 'exec', '-T', '-e', f'{variable}={value}', 'web', 'python',
                             'manage.py', 'check_runtime', '--require-redis', '--json'], check=False)
                status = json.loads(probe.stdout)
                assert probe.returncode != 0 and not status[expected]['ok'], 'Unavailable service was not detected'
                negative[expected + '_unavailable_detected'] = True
            (output / 'runtime-negative.json').write_text(json.dumps(negative, indent=2) + '\n')
            address = run([*compose, 'port', 'nginx', '443']).stdout.strip()
            port = address.rsplit(':', 1)[1]
            for path in ('/', '/login/', '/api/health/', '/static/css/style.css'):
                request = urllib.request.Request(f'https://127.0.0.1:{port}{path}', headers={'Host': 'localhost'})
                for attempt in range(30):
                    try:
                        with urllib.request.urlopen(request, context=ssl._create_unverified_context(), timeout=5) as response:
                            assert response.status == 200
                        break
                    except (OSError, urllib.error.URLError):
                        if attempt == 29:
                            raise
                        time.sleep(1)
            # Repeated headers must travel over HTTP; a WSGI dict cannot represent
            # them separately. Keep all samples small and below proxy limits.
            header_cases = {
                'quoted_content_type': [('Content-Type', 'text/plain; note="a;b;c"')],
                'quoted_accept': [('Accept', 'text/html; note="a;b;c", application/json;q=0.5')],
                'repeated_accept': [('Accept', 'text/html; note="a;b"'), ('Accept', 'application/json')],
                'repeated_content_type': [('Content-Type', 'text/plain; note="a;b"'),
                                          ('Content-Type', 'application/json')],
                'repeated_host': [('Host', 'localhost')],
            }
            header_results = {}
            for label, headers in header_cases.items():
                connection = http.client.HTTPSConnection('127.0.0.1', int(port), timeout=10,
                                                         context=ssl._create_unverified_context())
                try:
                    connection.putrequest('GET', '/api/health/', skip_host=True)
                    connection.putheader('Host', 'localhost')
                    for key, value in headers:
                        connection.putheader(key, value)
                    connection.endheaders()
                    response = connection.getresponse()
                    response.read()
                    # This stack accepts repeated Content-Type, but Nginx rejects
                    # duplicate Host headers before the request reaches Django.
                    expected = 400 if label == 'repeated_host' else 200
                    assert response.status == expected, (label, response.status, expected)
                    header_results[label] = {'status': response.status,
                                             'outcome': 'proxy_rejected' if expected == 400 else 'application_healthy'}
                finally:
                    connection.close()
            (output / 'header-http.json').write_text(json.dumps(header_results, indent=2) + '\n')
            print('Checking fresh setup with PostgreSQL and Redis...', flush=True)
            run([*compose, 'exec', '-T', 'db', 'createdb', '-U', 'entails_smoke', 'entails_smoke_setup'])
            setup = run([*compose, 'exec', '-T', '-e', 'ENTAILS_SETUP_SMOKE=1',
                         '-e', 'DB_NAME=entails_smoke_setup', 'web', 'python', 'scripts/setup_smoke.py'], check=False)
            (output / 'setup.json').write_text(setup.stdout)
            (output / 'setup.log').write_text(redact(setup.stderr))
            if setup.returncode:
                raise RuntimeError('Frisches Setup fehlgeschlagen; siehe setup.log.')
            if options.performance:
                print('Recording HTTP workloads through Nginx and Gunicorn...', flush=True)
                performance = run([*compose, 'exec', '-T', '-e', 'ENTAILS_PERF_TEST=1', 'web',
                                   'python', 'scripts/http_performance_smoke.py', '--base-url', 'http://nginx:8080'], check=False)
                (output / 'http-performance.json').write_text(performance.stdout)
                (output / 'http-performance.log').write_text(redact(performance.stderr))
                if performance.returncode:
                    raise RuntimeError('HTTP-Baseline fehlgeschlagen; siehe http-performance.json/.log.')
            states = run([*compose, 'ps', '--format', 'json']).stdout
            # Newer Compose emits one JSON object per line; older versions emit an array.
            states = json.loads(states) if states.strip().startswith('[') else [json.loads(line) for line in states.splitlines()]
            assert all(item['State'] == 'running' for item in states), 'Worker did not stay running'
            assert len(states) == 8, 'Expected web, database, Redis, Nginx and four workers'
            result = {'container': 'passed', 'services': sorted(item['Service'] for item in states),
                      'image_id': image_id, 'django': runtime['django'],
                      'django_suite': 'full' if options.tests else 'security',
                      'header_cases': len(header_results), 'https_pages': 4, 'real_smtp': False,
                      'external_tunnel_acme': 'not tested'}
            (output / 'container.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result), flush=True)
        finally:
            if started:
                logs = run([*compose, 'logs', '--no-color', '--tail=150'], check=False)
                (output / 'services.log').write_text(redact(logs.stdout + logs.stderr))
                run([*compose, 'down', '--volumes', '--remove-orphans'], check=False)
            run(['docker', 'image', 'rm', image], check=False)


if __name__ == '__main__':
    main()
