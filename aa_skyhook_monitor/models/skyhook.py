"""Skyhook Models"""

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from aa_skyhook_monitor.constants import BAY_VOLUME_M3
from aa_skyhook_monitor.managers import SkyhookManager


class RaidWatchRegion(models.Model):
    """Available nullsec regions for the raidable-skyhooks watchlist filter.

    Populated automatically from the SDE on each raidable sync.
    Admins select from these via the SkyhookConfiguration M2M filter.
    """

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        default_permissions = ()
        ordering = ["name"]

    def __str__(self):
        return self.name


class RaidWatchConstellation(models.Model):
    """Available nullsec constellations for the raidable-skyhooks watchlist filter."""

    name = models.CharField(max_length=100, unique=True)
    region_name = models.CharField(max_length=100)

    class Meta:
        default_permissions = ()
        ordering = ["region_name", "name"]

    def __str__(self):
        return f"{self.name} ({self.region_name})"


class SkyhookConfiguration(models.Model):
    discord_webhook_url = models.URLField(
        blank=True,
        help_text=_(
            "Discord webhook URL for own-skyhook notifications (empty = disabled)"
        ),
    )
    raidable_webhook_url = models.URLField(
        blank=True,
        help_text=_(
            "Discord webhook URL for raidable-skyhook alerts (empty = disabled)"
        ),
    )
    last_full_sync = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Timestamp of the last full ESI sync run"),
    )
    last_raidable_sync = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Timestamp of the last raidable-skyhooks fetch"),
    )
    watched_regions = models.ManyToManyField(
        RaidWatchRegion,
        blank=True,
        related_name="+",
        help_text=_("Show only raidable skyhooks in these regions (empty = show all)."),
    )
    watched_constellations = models.ManyToManyField(
        RaidWatchConstellation,
        blank=True,
        related_name="+",
        help_text=_(
            "Show only raidable skyhooks in these constellations (empty = show all)."
        ),
    )

    class Meta:
        default_permissions = ()

    def __str__(self):
        return "Skyhook Monitor Konfiguration"

    @classmethod
    def solo(cls):
        """Return the singleton config row, creating it if needed."""
        config = cls.objects.first()
        if config is None:
            config = cls.objects.create()
        return config

    @classmethod
    def get_webhook_url(cls):
        config = cls.objects.first()
        return (
            config.discord_webhook_url
            if config and config.discord_webhook_url
            else None
        )

    @classmethod
    def mark_synced(cls):
        config = cls.solo()
        config.last_full_sync = timezone.now()
        config.save(update_fields=["last_full_sync"])

    @classmethod
    def get_last_sync(cls):
        config = cls.objects.first()
        return config.last_full_sync if config else None

    @classmethod
    def mark_raidable_synced(cls):
        config = cls.solo()
        config.last_raidable_sync = timezone.now()
        config.save(update_fields=["last_raidable_sync"])

    @classmethod
    def get_raidable_last_sync(cls):
        config = cls.objects.first()
        return config.last_raidable_sync if config else None


class SkyhookOwner(models.Model):
    corporation = models.OneToOneField(
        EveCorporationInfo, on_delete=models.CASCADE, related_name="skyhook_owner"
    )
    character = models.ForeignKey(
        EveCharacter,
        on_delete=models.SET_NULL,
        null=True,
        help_text=_("Character whose ESI token is used for API queries"),
    )
    last_updated = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_permissions = ()
        permissions = (
            ("view_skyhooks", "Can view Skyhook bay contents"),
            ("manage_skyhooks", "Can add and remove corporations"),
        )

    def __str__(self):
        return self.corporation.corporation_name


class Skyhook(models.Model):
    owner = models.ForeignKey(
        SkyhookOwner, on_delete=models.CASCADE, related_name="skyhooks"
    )
    structure_id = models.BigIntegerField(unique=True)
    planet_id = models.IntegerField(null=True, blank=True)
    planet_name = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=False)
    state = models.CharField(max_length=50, blank=True)
    theft_vulnerability_start = models.DateTimeField(null=True, blank=True)
    theft_vulnerability_end = models.DateTimeField(null=True, blank=True)
    notified_warning_for = models.DateTimeField(null=True, blank=True)
    notified_start_for = models.DateTimeField(null=True, blank=True)

    objects = SkyhookManager()

    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.planet_name or str(self.structure_id)

    @property
    def is_currently_vulnerable(self):
        if not self.theft_vulnerability_start or not self.theft_vulnerability_end:
            return False
        now = timezone.now()
        return self.theft_vulnerability_start <= now <= self.theft_vulnerability_end

    @property
    def vuln_is_expired(self):
        if not self.theft_vulnerability_start:
            return False
        now = timezone.now()
        if self.theft_vulnerability_start > now:
            return False
        if self.theft_vulnerability_end:
            return self.theft_vulnerability_end < now
        return True


class RaidableSkyhook(models.Model):
    """Public raidable skyhooks fetched from /skyhooks/raidable (no auth required).

    Persistent table — new entries are upserted, expired ones pruned.
    Unique on (planet_id, theft_vulnerability_start) so the same window is
    never inserted twice. notified tracks whether a Discord ping was sent.
    """

    planet_id = models.IntegerField()
    planet_name = models.CharField(max_length=100, blank=True)
    solar_system_id = models.IntegerField(db_index=True)
    solar_system_name = models.CharField(max_length=100)
    security_status = models.FloatField(default=0)
    constellation_name = models.CharField(max_length=100)
    region_name = models.CharField(max_length=100)
    theft_vulnerability_start = models.DateTimeField()
    theft_vulnerability_end = models.DateTimeField()
    notified = models.BooleanField(default=False)

    class Meta:
        default_permissions = ()
        ordering = ["theft_vulnerability_start"]
        unique_together = ("planet_id", "theft_vulnerability_start")

    def __str__(self):
        return f"{self.solar_system_name} / {self.planet_id}"

    @property
    def is_currently_vulnerable(self):
        now = timezone.now()
        return self.theft_vulnerability_start <= now <= self.theft_vulnerability_end

    @property
    def vuln_is_expired(self):
        return self.theft_vulnerability_end < timezone.now()


class SkyhookReagent(models.Model):
    skyhook = models.ForeignKey(
        Skyhook, on_delete=models.CASCADE, related_name="reagents"
    )
    type_id = models.IntegerField()
    type_name = models.CharField(max_length=255, blank=True)
    volume = models.FloatField(default=0)
    secured_stock = models.BigIntegerField(default=0)
    unsecured_stock = models.BigIntegerField(default=0)

    class Meta:
        default_permissions = ()
        unique_together = ("skyhook", "type_id")

    @property
    def secured_m3(self):
        return round(self.secured_stock * self.volume)

    @property
    def unsecured_m3(self):
        return round(self.unsecured_stock * self.volume)

    @property
    def secured_pct(self):
        return min(100, round(self.secured_m3 / BAY_VOLUME_M3 * 100))

    @property
    def unsecured_pct(self):
        return min(100, round(self.unsecured_m3 / BAY_VOLUME_M3 * 100))
