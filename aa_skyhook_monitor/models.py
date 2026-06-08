from django.db import models
from django.utils import timezone
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo

BAY_VOLUME_M3 = 10468


class SkyhookConfiguration(models.Model):
    discord_webhook_url = models.URLField(
        blank=True,
        help_text='Discord Webhook URL für Skyhook-Notifications (leer = deaktiviert)'
    )

    class Meta:
        default_permissions = ()

    def __str__(self):
        return 'Skyhook Monitor Konfiguration'

    @classmethod
    def get_webhook_url(cls):
        config = cls.objects.first()
        return config.discord_webhook_url if config and config.discord_webhook_url else None


class SkyhookOwner(models.Model):
    corporation = models.OneToOneField(
        EveCorporationInfo, on_delete=models.CASCADE, related_name='skyhook_owner'
    )
    character = models.ForeignKey(
        EveCharacter, on_delete=models.SET_NULL, null=True,
        help_text='Charakter dessen ESI-Token für API-Abfragen genutzt wird'
    )
    last_updated = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_permissions = ()
        permissions = (
            ('view_skyhooks', 'Can view Skyhook bay contents'),
            ('manage_skyhooks', 'Can add and remove corporations'),
        )

    def __str__(self):
        return self.corporation.corporation_name


class Skyhook(models.Model):
    owner = models.ForeignKey(
        SkyhookOwner, on_delete=models.CASCADE, related_name='skyhooks'
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


class SkyhookReagent(models.Model):
    skyhook = models.ForeignKey(
        Skyhook, on_delete=models.CASCADE, related_name='reagents'
    )
    type_id = models.IntegerField()
    type_name = models.CharField(max_length=255, blank=True)
    volume = models.FloatField(default=0)
    secured_stock = models.BigIntegerField(default=0)
    unsecured_stock = models.BigIntegerField(default=0)

    class Meta:
        default_permissions = ()
        unique_together = ('skyhook', 'type_id')

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
