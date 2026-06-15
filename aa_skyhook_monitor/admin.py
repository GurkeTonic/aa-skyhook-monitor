from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from .models import (
    RaidableSkyhook,
    RaidWatchConstellation,
    RaidWatchRegion,
    Skyhook,
    SkyhookConfiguration,
    SkyhookOwner,
    SkyhookReagent,
)


@admin.register(SkyhookConfiguration)
class SkyhookConfigurationAdmin(admin.ModelAdmin):
    actions = ["send_test_ping", "delete_selected"]
    filter_horizontal = ("watched_regions", "watched_constellations")

    def has_add_permission(self, request):
        return not SkyhookConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return True

    @admin.action(description=_("Send ping test"))
    def send_test_ping(self, request, queryset):
        from .tasks import _build_reagent_lines, _format_dt, _send_discord

        skyhook = (
            Skyhook.objects.filter(reagents__isnull=False)
            .select_related("owner__corporation")
            .first()
        )
        if not skyhook:
            self.message_user(
                request, _("No skyhooks with reagents found."), level=messages.ERROR
            )
            return

        corp = skyhook.owner.corporation.corporation_name
        start = _format_dt(skyhook.theft_vulnerability_start)
        end = _format_dt(skyhook.theft_vulnerability_end)
        reagents = _build_reagent_lines(skyhook)
        embeds = [
            {
                "title": "⏰ [TEST] Skyhook bald vulnerable",
                "color": 0xFFA500,
                "description": f"**{corp}** · {skyhook.planet_name}\n`{start} → {end} EVE`\n{reagents}",
                "footer": {"text": "AA Skyhook Monitor · Test"},
            },
            {
                "title": "🚨 [TEST] Skyhook VULNERABLE",
                "color": 0xFF0000,
                "description": f"**{corp}** · {skyhook.planet_name}\n`Ende: {end} EVE`\n{reagents}",
                "footer": {"text": "AA Skyhook Monitor · Test"},
            },
        ]

        for config in queryset:
            if not config.discord_webhook_url:
                self.message_user(
                    request, _("No webhook configured."), level=messages.WARNING
                )
                continue
            try:
                _send_discord(
                    {"embeds": embeds}, webhook_url=config.discord_webhook_url
                )
                self.message_user(
                    request,
                    _("Test ping sent (Skyhook: %(planet)s).")
                    % {"planet": skyhook.planet_name},
                )
            except Exception as e:
                self.message_user(
                    request,
                    _("Webhook error: %(err)s") % {"err": e},
                    level=messages.ERROR,
                )


@admin.register(SkyhookOwner)
class SkyhookOwnerAdmin(admin.ModelAdmin):
    list_display = ["corporation", "character", "last_updated"]
    actions = ["update_now"]

    @admin.action(description=_("Update from ESI now"))
    def update_now(self, request, queryset):
        from .tasks import update_owner_skyhooks

        for owner in queryset:
            update_owner_skyhooks.delay(owner.pk)
        self.message_user(
            request, _("%(count)d update(s) triggered.") % {"count": queryset.count()}
        )


@admin.register(Skyhook)
class SkyhookAdmin(admin.ModelAdmin):
    list_display = [
        "planet_name",
        "owner",
        "is_active",
        "state",
        "theft_vulnerability_start",
    ]
    list_filter = ["owner", "is_active"]
    readonly_fields = [
        "structure_id",
        "planet_id",
        "planet_name",
        "is_active",
        "state",
        "owner",
        "theft_vulnerability_start",
        "theft_vulnerability_end",
    ]


@admin.register(SkyhookReagent)
class SkyhookReagentAdmin(admin.ModelAdmin):
    list_display = ["skyhook", "type_name", "secured_stock", "unsecured_stock"]
    search_fields = ["type_name", "skyhook__planet_name"]


@admin.register(RaidableSkyhook)
class RaidableSkyhookAdmin(admin.ModelAdmin):
    list_display = [
        "region_name",
        "constellation_name",
        "solar_system_name",
        "planet_name",
        "theft_vulnerability_start",
        "theft_vulnerability_end",
        "notified",
    ]
    list_filter = ["region_name", "constellation_name", "notified"]
    search_fields = [
        "solar_system_name",
        "planet_name",
        "region_name",
        "constellation_name",
    ]
    ordering = ["theft_vulnerability_start"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
