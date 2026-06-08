import logging
import requests
from celery import shared_task
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from esi.models import Token
from .models import SkyhookOwner, Skyhook, SkyhookReagent

logger = logging.getLogger(__name__)
REQUIRED_SCOPES = ['esi-structures.read_corporation.v1']
ESI_BASE = 'https://esi.evetech.net'
ESI_HEADERS = {'X-Compatibility-Date': '2026-05-19'}


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
    url = f'{ESI_BASE}{path}'
    headers = {**ESI_HEADERS, 'Authorization': f'Bearer {token.valid_access_token()}'}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


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
        data = _esi_get(f'/corporations/{corporation_id}/structures/skyhooks', token)
        skyhook_list = data.get('skyhooks', [])
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
