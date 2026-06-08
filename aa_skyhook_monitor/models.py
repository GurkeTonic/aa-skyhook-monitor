from django.db import models
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo


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

    def __str__(self):
        return self.corporation.corporation_name


class Skyhook(models.Model):
    owner = models.ForeignKey(
        SkyhookOwner, on_delete=models.CASCADE, related_name='skyhooks'
    )
    structure_id = models.BigIntegerField(unique=True)
    structure_name = models.CharField(max_length=255)
    planet_id = models.IntegerField(null=True, blank=True)
    planet_name = models.CharField(max_length=100, blank=True)

    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.structure_name


class SkyhookBayItem(models.Model):
    skyhook = models.ForeignKey(
        Skyhook, on_delete=models.CASCADE, related_name='bay_items'
    )
    type_id = models.IntegerField()
    type_name = models.CharField(max_length=255, blank=True)
    quantity = models.BigIntegerField()
    is_secure_bay = models.BooleanField()

    class Meta:
        default_permissions = ()
