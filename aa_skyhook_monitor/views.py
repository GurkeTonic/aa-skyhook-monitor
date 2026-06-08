import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.shortcuts import redirect, render
from esi.decorators import token_required
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from .models import SkyhookOwner, Skyhook

logger = logging.getLogger(__name__)
REQUIRED_SCOPES = ['esi-structures.read_corporation.v1']


@login_required
def index(request):
    skyhooks = (
        Skyhook.objects
        .filter(reagents__isnull=False)
        .distinct()
        .select_related('owner__corporation')
        .order_by(F('theft_vulnerability_start').asc(nulls_last=True))
    )
    skyhook_data = [
        {'skyhook': s, 'reagents': list(s.reagents.order_by('type_name'))}
        for s in skyhooks
    ]
    owners = SkyhookOwner.objects.select_related('corporation').order_by('corporation__corporation_name')
    return render(request, 'aa_skyhook_monitor/index.html', {
        'skyhook_data': skyhook_data,
        'owners': owners,
    })


@login_required
@token_required(scopes=REQUIRED_SCOPES)
def add_owner(request, token):
    try:
        character = EveCharacter.objects.get(character_id=token.character_id)
    except EveCharacter.DoesNotExist:
        messages.error(request, 'Charakter nicht in Auth gefunden.')
        return redirect('aa_skyhook_monitor:index')
    try:
        corporation = EveCorporationInfo.objects.get(corporation_id=character.corporation_id)
    except EveCorporationInfo.DoesNotExist:
        corporation = EveCorporationInfo.objects.create_corporation(character.corporation_id)
    SkyhookOwner.objects.update_or_create(
        corporation=corporation,
        defaults={'character': character}
    )
    messages.success(request, f'{corporation.corporation_name} zum Skyhook Monitor hinzugefügt.')
    return redirect('aa_skyhook_monitor:index')
