from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from allianceauth.services.hooks import get_extension_logger
from esi.decorators import token_required

from .models import Skyhook, SkyhookConfiguration, SkyhookOwner
from .tasks import REQUIRED_SCOPES

logger = get_extension_logger(__name__)


@permission_required("aa_skyhook_monitor.view_skyhooks")
def index(request):
    skyhooks = (
        Skyhook.objects.with_reagents()
        .select_related("owner__corporation")
        .ordered_by_vuln()
    )
    skyhook_data = [
        {"skyhook": s, "reagents": list(s.reagents.order_by("type_name"))}
        for s in skyhooks
    ]
    return render(
        request,
        "aa_skyhook_monitor/index.html",
        {
            "skyhook_data": skyhook_data,
            "last_sync": SkyhookConfiguration.get_last_sync(),
        },
    )


@permission_required("aa_skyhook_monitor.manage_skyhooks")
@token_required(scopes=REQUIRED_SCOPES)
def add_owner(request, token):
    try:
        character = EveCharacter.objects.get(character_id=token.character_id)
    except EveCharacter.DoesNotExist:
        messages.error(request, _("Character not found in Auth."))
        return redirect("aa_skyhook_monitor:index")
    try:
        corporation = EveCorporationInfo.objects.get(corporation_id=character.corporation_id)
    except EveCorporationInfo.DoesNotExist:
        corporation = EveCorporationInfo.objects.create_corporation(character.corporation_id)
    SkyhookOwner.objects.update_or_create(
        corporation=corporation, defaults={"character": character}
    )
    messages.success(
        request,
        _("%(corp)s added to Skyhook Monitor.") % {"corp": corporation.corporation_name},
    )
    return redirect("aa_skyhook_monitor:index")
