from email.utils import parsedate_to_datetime

import requests
from celery import shared_task
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from allianceauth.services.hooks import get_extension_logger
from esi.models import Token
from .models import SkyhookOwner, Skyhook, SkyhookReagent, SkyhookConfiguration

logger = get_extension_logger(__name__)
REQUIRED_SCOPES = ['esi-structures.read_corporation.v1']
ESI_BASE = 'https://esi.evetech.net'
ESI_HEADERS = {'X-Compatibility-Date': '2026-05-19'}


def _get_user_agent():
    email = getattr(settings, 'ESI_USER_CONTACT_EMAIL', 'unknown@example.com')
    return f'aa-skyhook-monitor/0.1.2 ({email}; +https://github.com/GurkeTonic/aa-skyhook-monitor)'


def _handle_esi_response(resp):
    remain = int(resp.headers.get('X-ESI-Error-Limit-Remain', 100))
    if remain < 10:
        logger.warning(
            'ESI error limit critical: %d remaining, resets in %ss',
            remain, resp.headers.get('X-ESI-Error-Limit-Reset', '?'),
        )
    if resp.status_code == 429:
        logger.warning('ESI rate limited (429), retry after %ss', resp.headers.get('Retry-After', '?'))
    resp.raise_for_status()


def _cache_with_expires(cache_key, data, resp_headers):
    expires = resp_headers.get('Expires')
    if expires:
        try:
            exp_dt = parsedate_to_datetime(expires)
            ttl = max(60, int(exp_dt.timestamp() - timezone.now().timestamp()))
            cache.set(cache_key, data, timeout=ttl)
            return
        except Exception:
            pass
    cache.set(cache_key, data, timeout=300)


def _get_type_info(type_id):
    try:
        from eve_sde.models import ItemType
        t = ItemType.objects.get(id=type_id)
        return t.name, t.volume
    except Exception:
        return str(type_id), 0


def _get_planet_name(planet_id):
    try:
        from eve_sde.models import Planet
        return Planet.objects.get(id=planet_id).name
    except Exception:
        return str(planet_id)


def _esi_get(path, token):
    cache_key = f'esi_skyhook_{token.character_id}_{path}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    headers = {
        **ESI_HEADERS,
        'Authorization': f'Bearer {token.valid_access_token()}',
        'User-Agent': _get_user_agent(),
    }
    resp = requests.get(f'{ESI_BASE}{path}', headers=headers, timeout=30)
    _handle_esi_response(resp)
    data = resp.json()
    _cache_with_expires(cache_key, data, resp.headers)
    return data


def _esi_get_pages(path, token):
    results = []
    page = 1
    while True:
        cache_key = f'esi_skyhook_{token.character_id}_{path}_p{page}'
        cached = cache.get(cache_key)
        if cached is not None:
            data, total_pages = cached
        else:
            headers = {
                **ESI_HEADERS,
                'Authorization': f'Bearer {token.valid_access_token()}',
                'User-Agent': _get_user_agent(),
            }
            resp = requests.get(
                f'{ESI_BASE}{path}', headers=headers, params={'page': page}, timeout=30
            )
            _handle_esi_response(resp)
            data = resp.json()
            total_pages = int(resp.headers.get('X-Pages', 1))
            expires = resp.headers.get('Expires')
            ttl = 300
            if expires:
                try:
                    exp_dt = parsedate_to_datetime(expires)
                    ttl = max(60, int(exp_dt.timestamp() - timezone.now().timestamp()))
                except Exception:
                    pass
            cache.set(cache_key, (data, total_pages), timeout=ttl)
        if isinstance(data, list):
            results.extend(data)
        if page >= total_pages:
            break
        page += 1
    return results


def _format_dt(dt):
    return dt.strftime('%d.%m. %H:%M') if dt else '—'


def _build_reagent_text(skyhook):
    lines = []
    for r in skyhook.reagents.all():
        lines.append(
            f"**{r.type_name}**\n"
            f"Unsecured: {r.unsecured_stock:,} ({round(r.unsecured_stock * r.volume):,} m³) · "
            f"Secured: {r.secured_stock:,} ({round(r.secured_stock * r.volume):,} m³)"
        )
    return '\n'.join(lines) if lines else 'Keine Reagents'


def _send_discord(payload):
    webhook_url = SkyhookConfiguration.get_webhook_url()
    if not webhook_url:
        return
    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        logger.error('Discord webhook failed: %s', e)


def _send_warning_ping(skyhook):
    embed = {
        'title': '⏰ Skyhook bald vulnerable',
        'color': 0xFFA500,
        'fields': [
            {'name': 'Corp', 'value': skyhook.owner.corporation.corporation_name, 'inline': True},
            {'name': 'Planet', 'value': skyhook.planet_name, 'inline': True},
            {'name': '\u200b', 'value': '\u200b', 'inline': False},
            {'name': 'Vuln Start', 'value': f"{_format_dt(skyhook.theft_vulnerability_start)} EVE", 'inline': True},
            {'name': 'Vuln End', 'value': f"{_format_dt(skyhook.theft_vulnerability_end)} EVE", 'inline': True},
            {'name': 'Reagents', 'value': _build_reagent_text(skyhook), 'inline': False},
        ],
        'footer': {'text': 'AA Skyhook Monitor'},
    }
    _send_discord({'content': '@here', 'embeds': [embed]})


def _send_start_ping(skyhook):
    embed = {
        'title': '🚨 Skyhook VULNERABLE',
        'color': 0xFF0000,
        'fields': [
            {'name': 'Corp', 'value': skyhook.owner.corporation.corporation_name, 'inline': True},
            {'name': 'Planet', 'value': skyhook.planet_name, 'inline': True},
            {'name': '\u200b', 'value': '\u200b', 'inline': False},
            {'name': 'Vuln endet um', 'value': f"{_format_dt(skyhook.theft_vulnerability_end)} EVE", 'inline': True},
            {'name': 'Reagents', 'value': _build_reagent_text(skyhook), 'inline': False},
        ],
        'footer': {'text': 'AA Skyhook Monitor'},
    }
    _send_discord({'content': '@everyone', 'embeds': [embed]})


@shared_task
def check_skyhook_notifications():
    if not SkyhookConfiguration.get_webhook_url():
        return
    now = timezone.now()

    # Vorwarnung: Vuln startet in 25-35 Minuten
    warning_from = now + timedelta(minutes=25)
    warning_to = now + timedelta(minutes=35)
    for skyhook in Skyhook.objects.filter(
        theft_vulnerability_start__gte=warning_from,
        theft_vulnerability_start__lte=warning_to,
        reagents__isnull=False,
    ).exclude(notified_warning_for=F('theft_vulnerability_start')).distinct():
        _send_warning_ping(skyhook)
        skyhook.notified_warning_for = skyhook.theft_vulnerability_start
        skyhook.save(update_fields=['notified_warning_for'])

    # Start-Ping: Vuln hat gerade begonnen
    for skyhook in Skyhook.objects.filter(
        theft_vulnerability_start__lte=now,
        theft_vulnerability_end__gte=now,
        reagents__isnull=False,
    ).exclude(notified_start_for=F('theft_vulnerability_start')).distinct():
        _send_start_ping(skyhook)
        skyhook.notified_start_for = skyhook.theft_vulnerability_start
        skyhook.save(update_fields=['notified_start_for'])


@shared_task
def update_all_skyhooks():
    for owner_pk in SkyhookOwner.objects.values_list('pk', flat=True):
        update_owner_skyhooks.delay(owner_pk)


@shared_task
def update_owner_skyhooks(owner_pk):
    try:
        owner = SkyhookOwner.objects.get(pk=owner_pk)
    except SkyhookOwner.DoesNotExist:
        return
    token = Token.get_token(owner.character.character_id, REQUIRED_SCOPES)
    if not token:
        logger.warning('No token found for %s', owner)
        return
    corporation_id = owner.corporation.corporation_id
    try:
        skyhook_list = _esi_get_pages(f'/corporations/{corporation_id}/structures/skyhooks', token)
    except Exception as e:
        logger.error('Failed to fetch Skyhook list for %s: %s', owner, e)
        return
    for skyhook_data in skyhook_list:
        update_skyhook_detail.delay(
            owner_pk,
            corporation_id,
            skyhook_data['id'],
            skyhook_data.get('planet_id'),
        )
    owner.last_updated = timezone.now()
    owner.save()


@shared_task(rate_limit='15/m')
def update_skyhook_detail(owner_pk, corporation_id, skyhook_id, planet_id):
    try:
        owner = SkyhookOwner.objects.get(pk=owner_pk)
    except SkyhookOwner.DoesNotExist:
        return
    token = Token.get_token(owner.character.character_id, REQUIRED_SCOPES)
    if not token:
        return
    try:
        detail = _esi_get(f'/corporations/{corporation_id}/structures/skyhooks/{skyhook_id}', token)
    except Exception as e:
        logger.error('Failed to fetch Skyhook detail %s: %s', skyhook_id, e)
        return
    vuln = detail.get('theft_vulnerability', {})
    skyhook, _ = Skyhook.objects.update_or_create(
        structure_id=skyhook_id,
        defaults={
            'owner': owner,
            'planet_id': planet_id,
            'planet_name': _get_planet_name(planet_id) if planet_id else '',
            'is_active': detail.get('is_active', False),
            'state': detail.get('state', ''),
            'theft_vulnerability_start': parse_datetime(vuln['start']) if vuln.get('start') else None,
            'theft_vulnerability_end': parse_datetime(vuln['end']) if vuln.get('end') else None,
        }
    )
    skyhook.reagents.all().delete()
    for reagent in detail.get('reagents', []):
        type_name, type_volume = _get_type_info(reagent['type_id'])
        SkyhookReagent.objects.create(
            skyhook=skyhook,
            type_id=reagent['type_id'],
            type_name=type_name,
            volume=type_volume,
            secured_stock=reagent.get('secured_stock', 0),
            unsecured_stock=reagent.get('unsecured_stock', 0),
        )
