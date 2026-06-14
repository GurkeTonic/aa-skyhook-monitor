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

from .models import (
    RaidableSkyhook,
    RaidWatchConstellation,
    RaidWatchRegion,
    Skyhook,
    SkyhookConfiguration,
    SkyhookOwner,
    SkyhookReagent,
)

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


# ---------------------------------------------------------------------------
# Public raidable-skyhooks task (no auth required)
# ---------------------------------------------------------------------------
@shared_task(base=QueueOnce, once={"graceful": True}, time_limit=SKYHOOK_MONITOR_TASKS_TIME_LIMIT)
def update_raidable_skyhooks():
    """Fetch the public /skyhooks/raidable endpoint and refresh the local cache.

    Runs every 5 minutes (matching the ESI cache-age). The entire
    RaidableSkyhook table is replaced atomically on each successful fetch.
    No ESI token or scope required.
    """
    try:
        result = esi.client.Skyhooks.GetSkyhooksRaidable().result()
    except HTTPNotModified:
        logger.debug("Raidable skyhooks unchanged (304)")
        return
    except (ESIErrorLimitException, ESIBucketLimitException):
        raise
    except Exception as exc:
        logger.error("Failed to fetch raidable skyhooks: %s", exc)
        return

    raw_entries = list(getattr(result, "skyhooks", None) or [])
    if not raw_entries:
        logger.warning("Empty raidable skyhooks response")
        return

    try:
        from eve_sde.models import SolarSystem
    except ImportError:
        logger.error("eve_sde not available — cannot resolve system names for raidable skyhooks")
        return

    system_ids = {e.solar_system_id for e in raw_entries}
    systems = {
        ss.id: ss
        for ss in SolarSystem.objects.filter(id__in=system_ids).select_related(
            "constellation__region"
        )
    }

    planet_ids = {e.planet_id for e in raw_entries}
    try:
        from eve_sde.models import Planet as SdePlanet
        planets = {p.id: p.name for p in SdePlanet.objects.filter(id__in=planet_ids)}
    except Exception:
        planets = {}

    records = []
    for entry in raw_entries:
        solar_system = systems.get(entry.solar_system_id)
        if not solar_system:
            continue
        vuln = getattr(entry, "theft_vulnerability", None)
        records.append(
            RaidableSkyhook(
                planet_id=entry.planet_id,
                planet_name=planets.get(entry.planet_id, ""),
                solar_system_id=entry.solar_system_id,
                solar_system_name=solar_system.name,
                security_status=solar_system.security_status,
                constellation_name=solar_system.constellation.name,
                region_name=solar_system.constellation.region.name,
                theft_vulnerability_start=_to_dt(getattr(vuln, "start", None)) if vuln else None,
                theft_vulnerability_end=_to_dt(getattr(vuln, "end", None)) if vuln else None,
            )
        )

    # Upsert — new windows are inserted, existing ones skipped (ignore_conflicts).
    RaidableSkyhook.objects.bulk_create(records, ignore_conflicts=True)

    # Prune entries whose vulnerability window has closed and are no longer in the feed.
    feed_keys = {(r.planet_id, r.theft_vulnerability_start) for r in records}
    now = timezone.now()
    for stale in RaidableSkyhook.objects.filter(theft_vulnerability_end__lt=now):
        if (stale.planet_id, stale.theft_vulnerability_start) not in feed_keys:
            stale.delete()

    SkyhookConfiguration.mark_raidable_synced()
    logger.info("Synced raidable skyhooks (%d in feed, %d total in DB)",
                len(records), RaidableSkyhook.objects.count())

    _sync_raid_watchlist_options()
    _notify_new_raidable_skyhooks()


def _sync_raid_watchlist_options():
    """Populate RaidWatchRegion / RaidWatchConstellation from the SDE.

    Loads all nullsec constellations and their regions. Only adds new entries —
    never deletes, so admin M2M selections are preserved.
    """
    try:
        from eve_sde.models import Constellation as SdeConstellation
    except ImportError:
        logger.error("eve_sde not available — cannot populate raid watchlist options")
        return

    constellations = (
        SdeConstellation.objects.filter(solarsystem__security_status__lt=-0.05)
        .select_related("region")
        .distinct()
    )

    existing_regions = set(RaidWatchRegion.objects.values_list("name", flat=True))
    existing_consts = set(RaidWatchConstellation.objects.values_list("name", flat=True))

    new_regions = []
    new_consts = []
    seen_regions = set()

    for const in constellations:
        region_name = const.region.name
        if region_name not in existing_regions and region_name not in seen_regions:
            new_regions.append(RaidWatchRegion(name=region_name))
            seen_regions.add(region_name)
        if const.name not in existing_consts:
            new_consts.append(
                RaidWatchConstellation(name=const.name, region_name=region_name)
            )
            existing_consts.add(const.name)

    if new_regions:
        RaidWatchRegion.objects.bulk_create(new_regions, ignore_conflicts=True)
        logger.info("Added %d new watchlist regions", len(new_regions))
    if new_consts:
        RaidWatchConstellation.objects.bulk_create(new_consts, ignore_conflicts=True)
        logger.info("Added %d new watchlist constellations", len(new_consts))


def _notify_new_raidable_skyhooks():
    """Ping Discord for raidable skyhooks that haven't been notified yet.

    Applies the watched_regions / watched_constellations filter — only sends
    pings for skyhooks that would also appear on the filtered raidable view.
    Groups all new entries into a single Discord message.
    """
    config = SkyhookConfiguration.objects.first()
    webhook_url = config.raidable_webhook_url if config else None
    if not webhook_url:
        return

    from django.db.models import Q

    watched_regions = list(config.watched_regions.values_list("name", flat=True))
    watched_constellations = list(config.watched_constellations.values_list("name", flat=True))

    new_skyhooks = RaidableSkyhook.objects.filter(notified=False)
    if watched_regions or watched_constellations:
        new_skyhooks = new_skyhooks.filter(
            Q(region_name__in=watched_regions)
            | Q(constellation_name__in=watched_constellations)
        )
    new_skyhooks = list(new_skyhooks)

    if not new_skyhooks:
        return

    lines = []
    for s in new_skyhooks:
        start = _format_dt(s.theft_vulnerability_start)
        end = _format_dt(s.theft_vulnerability_end)
        lines.append(
            f"**{s.region_name}** · {s.constellation_name} · {s.solar_system_name}"
            f" · {s.planet_name or s.planet_id}\n`{start} → {end} EVE`"
        )

    description = "\n\n".join(lines)
    embed = {
        "title": f"🎯 {len(new_skyhooks)} raidbare Skyhook(s) verfügbar",
        "color": 0x3498DB,
        "description": description,
        "footer": {"text": "AA Skyhook Monitor · Raidable"},
    }
    _send_discord({"embeds": [embed]}, webhook_url=webhook_url)
    logger.info("Sent raidable notification for %d new skyhooks", len(new_skyhooks))

    RaidableSkyhook.objects.filter(pk__in=[s.pk for s in new_skyhooks]).update(notified=True)
