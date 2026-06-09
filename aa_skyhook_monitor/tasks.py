from datetime import timedelta
from email.utils import parsedate_to_datetime

import requests
from celery import shared_task

from django.conf import settings
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from allianceauth.services.hooks import get_extension_logger
from esi.models import Token

from aa_skyhook_monitor import __app_name_useragent__, __esi_compatibility_date__, __version__
from aa_skyhook_monitor.app_settings import (
    SKYHOOK_MONITOR_TASKS_TIME_LIMIT,
    SKYHOOK_MONITOR_WARNING_MINUTES,
)
from aa_skyhook_monitor.constants import (
    ESI_BASE,
    RELEVANT_PLANET_TYPE_IDS,
    RELEVANT_REAGENT_TYPE_IDS,
)
from .models import SkyhookOwner, Skyhook, SkyhookReagent, SkyhookConfiguration

logger = get_extension_logger(__name__)
REQUIRED_SCOPES = ["esi-structures.read_corporation.v1"]
ESI_HEADERS = {"X-Compatibility-Date": __esi_compatibility_date__}


def _get_user_agent():
    email = getattr(settings, "ESI_USER_CONTACT_EMAIL", "unknown@example.com")
    return f"{__app_name_useragent__}/{__version__} ({email}; +https://github.com/GurkeTonic/aa-skyhook-monitor)"


def _handle_esi_response(resp):
    remain = int(resp.headers.get("X-ESI-Error-Limit-Remain", 100))
    if remain <= 0:
        reset = resp.headers.get("X-ESI-Error-Limit-Reset", "?")
        logger.error("ESI error limit exhausted, resets in %ss — aborting", reset)
        resp.raise_for_status()
    if remain < 10:
        logger.warning(
            "ESI error limit critical: %d remaining, resets in %ss",
            remain,
            resp.headers.get("X-ESI-Error-Limit-Reset", "?"),
        )
    if resp.status_code == 429:
        logger.warning("ESI rate limited (429), retry after %ss", resp.headers.get("Retry-After", "?"))
    resp.raise_for_status()


def _cache_with_expires(cache_key, data, resp_headers):
    expires = resp_headers.get("Expires")
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
    cache_key = f"esi_skyhook_{token.character_id}_{path}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    headers = {
        **ESI_HEADERS,
        "Authorization": f"Bearer {token.valid_access_token()}",
        "User-Agent": _get_user_agent(),
    }
    resp = requests.get(f"{ESI_BASE}{path}", headers=headers, timeout=30)
    _handle_esi_response(resp)
    data = resp.json()
    total_pages = int(resp.headers.get("X-Pages", 1))
    if total_pages > 1 and isinstance(data, list):
        for page in range(2, total_pages + 1):
            paged_resp = requests.get(
                f"{ESI_BASE}{path}", headers=headers, params={"page": page}, timeout=30
            )
            _handle_esi_response(paged_resp)
            data.extend(paged_resp.json())
    _cache_with_expires(cache_key, data, resp.headers)
    return data


def _format_dt(dt):
    return dt.strftime("%d.%m. %H:%M") if dt else "—"


def _build_reagent_lines(skyhook):
    lines = []
    for r in skyhook.reagents.all():
        lines.append(f"**{r.type_name}** · {r.unsecured_stock:,} unsec / {r.secured_stock:,} sec")
    return "\n".join(lines) if lines else "—"


def _send_discord(payload):
    webhook_url = SkyhookConfiguration.get_webhook_url()
    if not webhook_url:
        return
    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        logger.error("Discord webhook failed: %s", e)


def _send_warning_ping(skyhook):
    corp = skyhook.owner.corporation.corporation_name
    start = _format_dt(skyhook.theft_vulnerability_start)
    end = _format_dt(skyhook.theft_vulnerability_end)
    desc = f"**{corp}** · {skyhook.planet_name}\n`{start} → {end} EVE`\n{_build_reagent_lines(skyhook)}"
    embed = {
        "title": "⏰ Skyhook bald vulnerable",
        "color": 0xFFA500,
        "description": desc,
        "footer": {"text": "AA Skyhook Monitor"},
    }
    _send_discord({"content": "@here", "embeds": [embed]})


def _send_start_ping(skyhook):
    corp = skyhook.owner.corporation.corporation_name
    end = _format_dt(skyhook.theft_vulnerability_end)
    desc = f"**{corp}** · {skyhook.planet_name}\n`Ende: {end} EVE`\n{_build_reagent_lines(skyhook)}"
    embed = {
        "title": "🚨 Skyhook VULNERABLE",
        "color": 0xFF0000,
        "description": desc,
        "footer": {"text": "AA Skyhook Monitor"},
    }
    _send_discord({"content": "@everyone", "embeds": [embed]})


@shared_task(time_limit=SKYHOOK_MONITOR_TASKS_TIME_LIMIT)
def check_skyhook_notifications():
    if not SkyhookConfiguration.get_webhook_url():
        return
    now = timezone.now()
    margin = timedelta(minutes=5)
    warning_from = now + timedelta(minutes=SKYHOOK_MONITOR_WARNING_MINUTES) - margin
    warning_to = now + timedelta(minutes=SKYHOOK_MONITOR_WARNING_MINUTES) + margin

    for skyhook in Skyhook.objects.filter(
        theft_vulnerability_start__gte=warning_from,
        theft_vulnerability_start__lte=warning_to,
        reagents__isnull=False,
    ).exclude(notified_warning_for=F("theft_vulnerability_start")).distinct():
        _send_warning_ping(skyhook)
        skyhook.notified_warning_for = skyhook.theft_vulnerability_start
        skyhook.save(update_fields=["notified_warning_for"])

    for skyhook in Skyhook.objects.filter(
        theft_vulnerability_start__lte=now,
        theft_vulnerability_end__gte=now,
        reagents__isnull=False,
    ).exclude(notified_start_for=F("theft_vulnerability_start")).distinct():
        _send_start_ping(skyhook)
        skyhook.notified_start_for = skyhook.theft_vulnerability_start
        skyhook.save(update_fields=["notified_start_for"])


@shared_task(time_limit=SKYHOOK_MONITOR_TASKS_TIME_LIMIT)
def update_all_skyhooks():
    for owner_pk in SkyhookOwner.objects.values_list("pk", flat=True):
        update_owner_skyhooks.delay(owner_pk)


@shared_task(time_limit=SKYHOOK_MONITOR_TASKS_TIME_LIMIT)
def update_owner_skyhooks(owner_pk):
    try:
        owner = SkyhookOwner.objects.get(pk=owner_pk)
    except SkyhookOwner.DoesNotExist:
        return
    token = Token.get_token(owner.character.character_id, REQUIRED_SCOPES)
    if not token:
        logger.warning("No token found for %s", owner)
        return
    corporation_id = owner.corporation.corporation_id
    try:
        response = _esi_get(f"/corporations/{corporation_id}/structures/skyhooks", token)
    except Exception as e:
        logger.error("Failed to fetch Skyhook list for %s: %s", owner, e)
        return
    if isinstance(response, dict):
        skyhook_list = response.get("skyhooks", [])
    else:
        skyhook_list = response
    if not skyhook_list:
        logger.warning("Empty skyhook list for %s — raw response: %s", owner, response)
        return
    from eve_sde.models import Planet as SdePlanet

    relevant_planet_ids = set(
        SdePlanet.objects.filter(
            id__in=[s["planet_id"] for s in skyhook_list if s.get("planet_id")],
            item_type_id__in=RELEVANT_PLANET_TYPE_IDS,
        ).values_list("id", flat=True)
    )
    relevant_structure_ids = {
        s["id"] for s in skyhook_list if s.get("planet_id") in relevant_planet_ids
    }
    deleted, _ = Skyhook.objects.exclude(structure_id__in=relevant_structure_ids).delete()
    if deleted:
        logger.info("Deleted %d irrelevant skyhook records for %s", deleted, owner)
    for skyhook_data in skyhook_list:
        planet_id = skyhook_data.get("planet_id")
        if planet_id not in relevant_planet_ids:
            continue
        update_skyhook_detail.delay(
            owner_pk,
            corporation_id,
            skyhook_data["id"],
            planet_id,
        )
    owner.last_updated = timezone.now()
    owner.save()


@shared_task(rate_limit="15/m", time_limit=SKYHOOK_MONITOR_TASKS_TIME_LIMIT)
def update_skyhook_detail(owner_pk, corporation_id, skyhook_id, planet_id):
    try:
        owner = SkyhookOwner.objects.get(pk=owner_pk)
    except SkyhookOwner.DoesNotExist:
        return
    token = Token.get_token(owner.character.character_id, REQUIRED_SCOPES)
    if not token:
        return
    path = f"/corporations/{corporation_id}/structures/skyhooks/{skyhook_id}"
    try:
        existing = Skyhook.objects.get(structure_id=skyhook_id)
        if existing.theft_vulnerability_end and existing.theft_vulnerability_end < timezone.now():
            cache.delete(f"esi_skyhook_{token.character_id}_{path}")
    except Skyhook.DoesNotExist:
        pass
    try:
        detail = _esi_get(path, token)
    except Exception as e:
        logger.error("Failed to fetch Skyhook detail %s: %s", skyhook_id, e)
        return
    relevant_reagents = [
        r for r in detail.get("reagents", []) if r["type_id"] in RELEVANT_REAGENT_TYPE_IDS
    ]
    if not relevant_reagents:
        Skyhook.objects.filter(structure_id=skyhook_id).delete()
        return
    vuln = detail.get("theft_vulnerability", {})
    skyhook, _ = Skyhook.objects.update_or_create(
        structure_id=skyhook_id,
        defaults={
            "owner": owner,
            "planet_id": planet_id,
            "planet_name": _get_planet_name(planet_id) if planet_id else "",
            "is_active": detail.get("is_active", False),
            "state": detail.get("state", ""),
            "theft_vulnerability_start": parse_datetime(vuln["start"]) if vuln.get("start") else None,
            "theft_vulnerability_end": parse_datetime(vuln["end"]) if vuln.get("end") else None,
        },
    )
    skyhook.reagents.all().delete()
    for reagent in relevant_reagents:
        type_name, type_volume = _get_type_info(reagent["type_id"])
        SkyhookReagent.objects.create(
            skyhook=skyhook,
            type_id=reagent["type_id"],
            type_name=type_name,
            volume=type_volume,
            secured_stock=reagent.get("secured_stock", 0),
            unsecured_stock=reagent.get("unsecured_stock", 0),
        )
