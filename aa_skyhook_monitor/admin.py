from django.contrib import admin
from .models import SkyhookConfiguration, SkyhookOwner, Skyhook, SkyhookReagent


@admin.register(SkyhookConfiguration)
class SkyhookConfigurationAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not SkyhookConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


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
