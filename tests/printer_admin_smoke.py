"""Real HTTP admin setup checks for disposable printer deployment runners."""
import http.client
import http.cookiejar
import json
from pathlib import Path
import re
import secrets
import sys
import urllib.parse
import urllib.request


def check_public_routes(base):
    target = urllib.parse.urlsplit(base)
    for path, expected in (('/system/print-control', 302), ('/settings', 302),
                           ('/api/status', 401), ('/login', 200)):
        connection = http.client.HTTPConnection(target.hostname, target.port, timeout=10)
        try:
            connection.request('GET', path)
            response = connection.getresponse()
            assert response.status == expected, (path, response.status)
            if expected == 302:
                assert response.getheader('Location').startswith('/login?next=')
            response.read()
        finally:
            connection.close()


def sign_in(browser, base, credential):
    def page(path):
        with browser.open(base + path, timeout=15) as response:
            assert response.status == 200
            return response.read().decode(), urllib.parse.urlsplit(response.url).path

    def post(path, html, values):
        csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
        request = urllib.request.Request(base + path,
            data=urllib.parse.urlencode(dict(values, csrf=csrf, next='/settings')).encode(),
            headers={'Origin': base})
        with browser.open(request, timeout=15) as response:
            assert response.status == 200
            return response.read().decode(), urllib.parse.urlsplit(response.url).path

    html, _ = page('/login')
    html, path = post('/login', html, credential)
    assert path == '/change-password', 'A new installation must require changing its temporary password.'
    password = secrets.token_urlsafe(24)
    html, path = post('/change-password', html, dict(current_password=credential['password'],
                     new_password=password, confirmation=password))
    assert path == '/settings' and 'name="revision"' in html
    html, path = page('/system/print-control')
    assert path == '/system/print-control' and 'Print Control' in html


def main():
    base = 'http://127.0.0.1:5055'
    check_public_routes(base)
    credential_path = Path(sys.argv[1])
    assert credential_path.stat().st_mode & 0o777 == 0o600
    browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    sign_in(browser, base, json.loads(credential_path.read_text()))
    credential_path.unlink()
    print('PASS: protected admin pages, temporary login, required password change, and authenticated settings.')


if __name__ == '__main__':
    main()
