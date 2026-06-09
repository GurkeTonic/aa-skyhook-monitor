from django.contrib import admin, messages
from .models import SkyhookConfiguration, SkyhookOwner, Skyhook, SkyhookReagent


@admin.register(SkyhookConfiguration)
class SkyhookConfigurationAdmin(admin.ModelAdmin):
    actions = ['send_test_ping', 'delete_selected']

    def has_add_permission(self, request):
        return not SkyhookConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return True

    @admin.action(description='🔔 Ping Test senden')
    def send_test_ping(self, request, queryset):
        from .tasks import _send_warning_ping, _send_start_ping, _format_dt, _build_reagent_lines, _send_discord
        import requests as req

        skyhook = Skyhook.objects.filter(reagents__isnull=False).select_related('owner__corporation').first()
        if not skyhook:
            self.message_user(request, 'Keine Skyhooks mit Reagents gefunden.', level=messages.ERROR)
            return

        for config in queryset:
            if not config.discord_webhook_url:
                self.message_user(request, f'Kein Webhook in Konfiguration gesetzt.', level=messages.WARNING)
                continue

            corp = skyhook.owner.corporation.corporation_name
            start = _format_dt(skyhook.theft_vulnerability_start)
            end = _format_dt(skyhook.theft_vulnerability_end)
            reagents = _build_reagent_lines(skyhook)

            embeds = [
                {
                    'title': '⏰ [TEST] Skyhook bald vulnerable',
                    'color': 0xFFA500,
                    'description': f"**{corp}** · {skyhook.planet_name}\n`{start} → {end} EVE`\n{reagents}",
                    'footer': {'text': 'AA Skyhook Monitor · Test'},
                },
                {
                    'title': '🚨 [TEST] Skyhook VULNERABLE',
                    'color': 0xFF0000,
                    'description': f"**{corp}** · {skyhook.planet_name}\n`Ende: {end} EVE`\n{reagents}",
                    'footer': {'text': 'AA Skyhook Monitor · Test'},
                },
            ]
            try:
                resp = req.post(config.discord_webhook_url, json={'embeds': embeds}, timeout=10)
                resp.raise_for_status()
                self.message_user(request, f'Test-Ping gesendet (Skyhook: {skyhook.planet_name}).')
            except Exception as e:
                self.message_user(request, f'Webhook-Fehler: {e}', level=messages.ERROR)


@admin.register(SkyhookOwner)
class SkyhookOwnerAdmin(admin.ModelAdmin):
    list_display = ['corporation', 'character', 'last_updated']
    actions = ['update_now']

    @admin.action(description='Jetzt von ESI aktualisieren')
    def update_now(self, request, queryset):
        from .tasks import update_owner_skyhooks
        for owner in queryset:
            update_owner_skyhooks.delay(owner.pk)
        self.message_user(request, f'{queryset.count()} Update(s) angestoßen.')


@admin.register(Skyhook)
class SkyhookAdmin(admin.ModelAdmin):
    list_display = ['planet_name', 'owner', 'is_active', 'theft_vulnerability_start']
    list_filter = ['owner', 'is_active']
    readonly_fields = ['structure_id', 'planet_id', 'planet_name', 'is_active', 'state', 'owner',
                       'theft_vulnerability_start', 'theft_vulnerability_end']


@admin.register(SkyhookReagent)
class SkyhookReagentAdmin(admin.ModelAdmin):
    list_display = ['skyhook', 'type_name', 'secured_stock', 'unsecured_stock']
    search_fields = ['type_name', 'skyhook__planet_name']
