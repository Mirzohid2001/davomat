"""
ERP Isomerix → Davomat (isomer-davomat.uz) SSO consume.

Xavfsiz qoidalar:
- PORTAL_SSO_SECRET / ERP_SSO_VERIFY_URL bo‘sh → oddiy /login/
- Token/tarmoq xato → oddiy /login/
- Default: faqat mavjud local username login qilinadi
- Eski login_view o‘zgarishsiz

ERP: PortalProject code=davomat, sso_consume_url=
https://isomer-davomat.uz/sso/erp/consume/
"""
from __future__ import annotations

import json
import logging
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.shortcuts import redirect
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)

User = get_user_model()


def _sso_configured() -> bool:
    secret = (getattr(settings, 'PORTAL_SSO_SECRET', None) or '').strip()
    verify = (getattr(settings, 'ERP_SSO_VERIFY_URL', None) or '').strip()
    return bool(secret and verify)


def _safe_next(raw: str | None) -> str:
    candidate = (raw or '').strip() or getattr(
        settings, 'LOGIN_REDIRECT_URL', '/dashboard/',
    ) or '/dashboard/'
    if not candidate.startswith('/') or candidate.startswith('//'):
        return '/dashboard/'
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return '/dashboard/'
    return candidate


def _verify_with_erp(token: str) -> dict | None:
    verify_url = (getattr(settings, 'ERP_SSO_VERIFY_URL', None) or '').strip()
    secret = (getattr(settings, 'PORTAL_SSO_SECRET', None) or '').strip()
    if not verify_url or not secret:
        return None
    project = getattr(settings, 'ERP_SSO_PROJECT_CODE', 'davomat') or 'davomat'
    timeout = int(getattr(settings, 'ERP_SSO_TIMEOUT_SEC', 10) or 10)
    payload = json.dumps({'token': token, 'project': project}).encode('utf-8')
    req = urlrequest.Request(
        verify_url,
        data=payload,
        headers={
            'X-Portal-SSO-Secret': secret,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
        method='POST',
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8')
            status = getattr(resp, 'status', 200)
    except urlerror.HTTPError as exc:
        logger.warning('ERP SSO verify HTTP %s', exc.code)
        return None
    except urlerror.URLError as exc:
        logger.warning('ERP SSO verify network error: %s', exc)
        return None
    except TimeoutError as exc:
        logger.warning('ERP SSO verify timeout: %s', exc)
        return None

    if status != 200:
        return None
    try:
        data = json.loads(body or '{}')
    except ValueError:
        return None
    if not data.get('ok') or not isinstance(data.get('user'), dict):
        return None
    return data


def _resolve_local_user(erp_user: dict):
    username = (erp_user.get('username') or '').strip()
    if not username:
        return None

    user = User.objects.filter(username=username).first()
    if user:
        return user if user.is_active else None

    auto_create = getattr(settings, 'ERP_SSO_AUTO_CREATE_USER', False)
    if not auto_create:
        logger.info('ERP SSO: local user %r yo‘q (AUTO_CREATE=False)', username)
        return None

    user = User(
        username=username,
        email=(erp_user.get('email') or '')[:254],
        first_name=(erp_user.get('first_name') or '')[:150],
        last_name=(erp_user.get('last_name') or '')[:150],
    )
    user.set_unusable_password()
    user.save()
    logger.info('ERP SSO: created local user %s', username)
    return user


@require_GET
def erp_sso_consume(request):
    """GET /sso/erp/consume/?token=...&next=/dashboard/"""
    token = (request.GET.get('token') or '').strip()
    next_url = _safe_next(request.GET.get('next'))

    if not _sso_configured():
        messages.info(
            request,
            'ERP SSO sozlanmagan. Oddiy login orqali kiring.',
        )
        return redirect('login')

    if not token:
        messages.error(request, 'SSO token topilmadi.')
        return redirect('login')

    data = _verify_with_erp(token)
    if not data:
        messages.error(
            request,
            'ERP SSO tekshiruvi muvaffaqiyatsiz. Oddiy login orqali kiring.',
        )
        return redirect('login')

    user = _resolve_local_user(data['user'])
    if user is None:
        messages.error(
            request,
            'Bu ERP foydalanuvchisi Davomatda topilmadi. '
            'Admin bir xil username yaratsin yoki oddiy login qiling.',
        )
        return redirect('login')

    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return redirect(next_url)
