"""Request compatibility checks for the Django header-parser security update."""
from io import BytesIO
import json
import subprocess
import sys
import textwrap

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.handlers.wsgi import WSGIRequest
from django.test import RequestFactory, SimpleTestCase


class HeaderParsingTests(SimpleTestCase):
    def request(self, content_type, body=b''):
        return WSGIRequest({
            'REQUEST_METHOD': 'POST', 'PATH_INFO': '/', 'SERVER_NAME': 'testserver',
            'SERVER_PORT': '80', 'wsgi.url_scheme': 'http', 'wsgi.input': BytesIO(body),
            'CONTENT_TYPE': content_type, 'CONTENT_LENGTH': str(len(body)),
        })

    def test_wsgi_constructor_preserves_type_charset_and_quoted_parameter(self):
        request = self.request('text/plain; charset="utf-8"; note="a;b;c"')
        self.assertEqual(request.content_type, 'text/plain')
        self.assertEqual(request.encoding, 'utf-8')
        self.assertEqual(request.content_params['note'], 'a;b;c')

    def test_rfc2231_parameter_without_encoding_is_decoded(self):
        request = self.request("text/plain; filename*=''report%20one.txt")
        self.assertEqual(request.content_params['filename'], 'report one.txt')

    def test_unusual_headers_do_not_crash_request_construction(self):
        for value in ('', 'text/plain;', 'text/plain; note="unterminated',
                      'application/json; charset=unknown-charset'):
            with self.subTest(value=value):
                self.assertIsInstance(self.request(value).content_params, dict)

    def test_accept_negotiation_with_quoted_separators(self):
        request = RequestFactory().get('/', HTTP_ACCEPT='text/html; note="a;b;c", application/json;q=0.5')
        self.assertTrue(request.accepts('application/json'))
        self.assertFalse(request.accepts('image/png'))
        self.assertEqual(request.get_preferred_type(['image/png', 'application/json']), 'application/json')

    def test_urlencoded_form_post_keeps_utf8_data(self):
        request = self.request('application/x-www-form-urlencoded; charset="utf-8"',
                               b'name=Gr%C3%BC%C3%9Fe&note=a%3Bb')
        self.assertEqual(request.POST['name'], 'Grüße')
        self.assertEqual(request.POST['note'], 'a;b')

    def test_multipart_post_preserves_fields_filename_and_file(self):
        request = RequestFactory().post('/', {
            'title': 'Grüße',
            'file': SimpleUploadedFile('report;one.txt', b'private attachment', content_type='text/plain'),
        })
        self.assertEqual(request.POST['title'], 'Grüße')
        self.assertEqual(request.FILES['file'].name, 'report;one.txt')
        self.assertEqual(request.FILES['file'].read(), b'private attachment')

    def test_bounded_separator_input_completes_in_terminable_process(self):
        # No public endpoint, concurrency, or timing benchmark. Bound both input
        # and execution so a future parser regression cannot hang the test runner.
        probe = textwrap.dedent('''
            from io import BytesIO
            import json
            from django.conf import settings
            settings.configure(DEFAULT_CHARSET='utf-8')
            from django.core.handlers.wsgi import WSGIRequest
            value = 'a;' * 4096
            request = WSGIRequest({
                'REQUEST_METHOD': 'GET', 'PATH_INFO': '/', 'SERVER_NAME': 'testserver',
                'SERVER_PORT': '80', 'wsgi.url_scheme': 'http', 'wsgi.input': BytesIO(),
                'CONTENT_TYPE': 'text/plain; note="' + value + '"',
                'HTTP_ACCEPT': 'text/plain; note="' + value + '"',
            })
            assert request.content_params['note'] == value
            assert request.accepts('image/png') is False
            print(json.dumps({'separators': 4096, 'completed': True}))
        ''')
        result = subprocess.run([sys.executable, '-c', probe], capture_output=True,
                                text=True, timeout=15, check=True)
        self.assertEqual(json.loads(result.stdout), {'separators': 4096, 'completed': True})
