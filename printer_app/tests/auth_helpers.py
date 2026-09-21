"""Explicit test access setup through the application's real authentication routes."""

ADMIN_PASSWORD = 'test-printer-admin-password-123'


def login_admin(client, *, base_url='http://localhost'):
    """Sign in, replace the initial password when needed, and return the live CSRF token."""
    temporary = client.application.extensions['printer_admin_auth'].ensure_temporary_password()
    password = temporary or ADMIN_PASSWORD
    assert client.get('/login', base_url=base_url).status_code == 200

    def csrf():
        with client.session_transaction(base_url=base_url) as session:
            return session['csrf']

    response = client.post('/login', base_url=base_url, headers={'Origin': base_url}, data={
        'csrf': csrf(), 'username': 'admin', 'password': password,
        'next': '/system/print-control',
    })
    assert response.status_code == 303
    if temporary:
        assert '/change-password?' in response.headers['Location']
        response = client.post('/change-password', base_url=base_url,
                               headers={'Origin': base_url}, data={
            'csrf': csrf(), 'current_password': temporary,
            'new_password': ADMIN_PASSWORD, 'confirmation': ADMIN_PASSWORD,
            'next': '/system/print-control',
        })
        assert response.status_code == 303
    assert client.get('/system/print-control', base_url=base_url).status_code == 200
    return csrf()


def browser_login(page, app, origin):
    """Use native forms so browser security tests retain real cookies and Origin behavior."""
    temporary = app.extensions['printer_admin_auth'].ensure_temporary_password()
    assert page.goto(origin + '/login').status == 200
    page.get_by_label('Username', exact=True).fill('admin')
    page.get_by_label('Password', exact=True).fill(temporary or ADMIN_PASSWORD)
    page.get_by_role('button', name='Sign in', exact=True).click()
    if temporary:
        page.wait_for_url(origin + '/change-password?**')
        page.get_by_label('Current password', exact=True).fill(temporary)
        page.get_by_label('New password', exact=True).fill(ADMIN_PASSWORD)
        page.get_by_label('Confirm new password', exact=True).fill(ADMIN_PASSWORD)
        page.get_by_role('button', name='Save new password', exact=True).click()
    page.wait_for_url(origin + '/system/print-control')


def gallery_client(app):
    """Enroll a new client using a real full-access Gallery invitation."""
    client = app.test_client()
    token = app.extensions['gallery_access'].issue_full_invite()
    assert client.get('/gallery/access/' + token, follow_redirects=True).status_code == 200
    return client


def open_gallery(page, app, origin):
    """Enroll a browser using the same invitation redemption a Gallery user follows."""
    token = app.extensions['gallery_access'].issue_full_invite()
    assert page.goto(origin + '/gallery/access/' + token).status == 200
