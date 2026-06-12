"""Celery tasks: ESI sync and Discord notifications.

ESI access goes through the django-esi OpenAPI client (see ``providers.py``),
which transparently handles caching, ETags, the floating-window rate limit,
the global error limit, the User-Agent and the compatibility date.
"""

from datetime import datetime, timedelta
from time import sleep

import requests
from celery import shared_task

from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from allianceauth.services.hooks import get_extension_logger
from allianceauth.services.tasks import QueueOnce
from esi.exceptions import ESIBucketLimitException, ESIErrorLimitException, HTTPNotModified
from esi.models import Token

from aa_skyhook_monitor.app_settings import (
    SKYHOOK_MONITOR_TASKS_TIME_LIMIT,
    SKYHOOK_MONITOR_WARNING_MINUTES,
)
from aa_skyhook_monitor.constants import (
    RELEVANT_PLANET_TYPE_IDS,
    RELEVANT_REAGENT_TYPE_IDS,
)
from aa_skyhook_monitor.providers import esi

from .models import Skyhook, SkyhookConfiguration, SkyhookOwner, SkyhookReagent

logger = get_extension_logger(__name__)

REQUIRED_SCOPES = ["esi-structures.read_corporation.v1"]

# Transient ESI limits — let Celery retry with backoff instead of failing.
ESI_RETRY = {
    "autoretry_for": (ESIErrorLimitException, ESIBucketLimitException),
    "retry_backoff": 30,
    "retry_kwargs": {"max_retries": 3},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _to_dt(value):
    """Return a datetime from an ESI value that may already be parsed or a string."""
    if value is None or isinstance(value, datetime):
        return value
    return parse_datetime(str(value))


def _get_type_info(type_id):
    """Resolve (name, volume) of a type from the local EVE SDE."""
    try:
        from eve_sde.models import ItemType

        item = ItemType.objects.get(id=type_id)
        return item.name, item.volume
    except Exception:
        return str(type_id), 0


def _get_planet_name(planet_id):
    """Resolve a planet name from the local EVE SDE."""
    try:
        from eve_sde.models import Planet

        return Planet.objects.get(id=planet_id).name
    except Exception:
        return str(planet_id)


def _format_dt(dt):
    return dt.strftime("%d.%m. %H:%M") if dt else "—"


def _build_reagent_lines(skyhook):
    lines = [
        f"**{r.type_name}** · {r.unsecured_stock:,} unsec / {r.secured_stock:,} sec"
        for r in skyhook.reagents.all()
    ]
    return "\n".join(lines) if lines else "—"


def _send_discord(payload, webhook_url=None):
    """Post a payload to a Discord webhook (with a small retry).

    Falls back to the configured webhook when ``webhook_url`` is not given.
    """
    webhook_url = webhook_url or SkyhookConfiguration.get_webhook_url()
    if not webhook_url:
        return
    for attempt in range(3):
        try:
            resp = requests.post(webhook_url, json=payload, timeout=10)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2))
                logger.warning("Discord rate limited, retry after %ss", retry_after)
                sleep(min(retry_after, 10))
                continue
            resp.raise_for_status()
            return
        except Exception as e:
            logger.error("Discord webhook failed (attempt %d/3): %s", attempt + 1, e)
            sleep(2 * (attempt + 1))
    logger.error("Discord webhook giving up after 3 attempts")


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


# ---------------------------------------------------------------------------
# Notification task
# ---------------------------------------------------------------------------
@shared_task(base=QueueOnce, once={"graceful": True}, time_limit=SKYHOOK_MONITOR_TASKS_TIME_LIMIT)
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


# ---------------------------------------------------------------------------
# ESI sync tasks
# ---------------------------------------------------------------------------
@shared_task(base=QueueOnce, once={"graceful": True}, time_limit=SKYHOOK_MONITOR_TASKS_TIME_LIMIT)
def update_all_skyhooks():
    for owner_pk in SkyhookOwner.objects.values_list("pk", flat=True):
        update_owner_skyhooks.delay(owner_pk)
    # Single, app-wide "last sync" marker shown in the UI.
    SkyhookConfiguration.mark_synced()


@shared_task(time_limit=SKYHOOK_MONITOR_TASKS_TIME_LIMIT, **ESI_RETRY)
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
        result = esi.client.Structures.GetCorporationsStructuresSkyhooksListing(
            corporation_id=corporation_id, token=token
        ).result()
    except HTTPNotModified:
        logger.debug("Skyhook listing unchanged for %s", owner)
        owner.last_updated = timezone.now()
        owner.save(update_fields=["last_updated"])
        return
    except (ESIErrorLimitException, ESIBucketLimitException):
        raise  # let autoretry handle it
    except Exception as e:
        logger.error("Failed to fetch Skyhook list for %s: %s", owner, e)
        return

    skyhook_list = list(getattr(result, "skyhooks", None) or [])
    if not skyhook_list:
        logger.warning("Empty skyhook list for %s", owner)
        return

    from eve_sde.models import Planet as SdePlanet

    candidate_planet_ids = [s.planet_id for s in skyhook_list if getattr(s, "planet_id", None)]
    relevant_planet_ids = set(
        SdePlanet.objects.filter(
            id__in=candidate_planet_ids,
            item_type_id__in=RELEVANT_PLANET_TYPE_IDS,
        ).values_list("id", flat=True)
    )
    relevant_structure_ids = {
        s.id for s in skyhook_list if s.planet_id in relevant_planet_ids
    }

    # Only prune *this owner's* stale records — never touch other owners' skyhooks.
    deleted, _ = (
        Skyhook.objects.filter(owner=owner)
        .exclude(structure_id__in=relevant_structure_ids)
        .delete()
    )
    if deleted:
        logger.info("Deleted %d irrelevant skyhook records for %s", deleted, owner)

    for skyhook in skyhook_list:
        if skyhook.planet_id not in relevant_planet_ids:
            continue
        update_skyhook_detail.delay(owner_pk, corporation_id, skyhook.id, skyhook.planet_id)

    owner.last_updated = timezone.now()
    owner.save(update_fields=["last_updated"])


@shared_task(rate_limit="15/m", time_limit=SKYHOOK_MONITOR_TASKS_TIME_LIMIT, **ESI_RETRY)
def update_skyhook_detail(owner_pk, corporation_id, skyhook_id, planet_id):
    try:
        owner = SkyhookOwner.objects.get(pk=owner_pk)
    except SkyhookOwner.DoesNotExist:
        return
    token = Token.get_token(owner.character.character_id, REQUIRED_SCOPES)
    if not token:
        return

    # If the stored vulnerability window has ended, bypass cache/ETag so we
    # immediately pick up the new schedule.
    force_refresh = False
    try:
        existing = Skyhook.objects.get(structure_id=skyhook_id)
        if existing.theft_vulnerability_end and existing.theft_vulnerability_end < timezone.now():
            force_refresh = True
    except Skyhook.DoesNotExist:
        pass

    try:
        detail = esi.client.Structures.GetCorporationsStructuresSkyhooksDetail(
            corporation_id=corporation_id, skyhook_id=skyhook_id, token=token
        ).result(force_refresh=force_refresh)
    except HTTPNotModified:
        logger.debug("Skyhook detail %s unchanged", skyhook_id)
        return
    except (ESIErrorLimitException, ESIBucketLimitException):
        raise
    except Exception as e:
        logger.error("Failed to fetch Skyhook detail %s: %s", skyhook_id, e)
        return

    reagents = list(getattr(detail, "reagents", None) or [])
    relevant_reagents = [r for r in reagents if r.type_id in RELEVANT_REAGENT_TYPE_IDS]
    if not relevant_reagents:
        Skyhook.objects.filter(structure_id=skyhook_id).delete()
        return

    vuln = getattr(detail, "theft_vulnerability", None)
    skyhook, _ = Skyhook.objects.update_or_create(
        structure_id=skyhook_id,
        defaults={
            "owner": owner,
            "planet_id": planet_id,
            "planet_name": _get_planet_name(planet_id) if planet_id else "",
            "is_active": bool(getattr(detail, "is_active", False)),
            "state": getattr(detail, "state", "") or "",
            "theft_vulnerability_start": _to_dt(getattr(vuln, "start", None)) if vuln else None,
            "theft_vulnerability_end": _to_dt(getattr(vuln, "end", None)) if vuln else None,
        },
    )

    skyhook.reagents.all().delete()
    for reagent in relevant_reagents:
        type_name, type_volume = _get_type_info(reagent.type_id)
        SkyhookReagent.objects.create(
            skyhook=skyhook,
            type_id=reagent.type_id,
            type_name=type_name,
            volume=type_volume,
            secured_stock=getattr(reagent, "secured_stock", 0) or 0,
            unsecured_stock=getattr(reagent, "unsecured_stock", 0) or 0,
        )
