from django.contrib import admin
from .models import SkyhookOwner, Skyhook, SkyhookReagent


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
    list_display = ['planet_name', 'owner', 'is_active']
    readonly_fields = ['structure_id', 'planet_id', 'planet_name', 'is_active', 'owner']
