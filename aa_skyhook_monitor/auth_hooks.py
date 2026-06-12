from django.utils.translation import gettext_lazy as _

from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook
import aa_skyhook_monitor.urls


class SkyhookMenuItemHook(MenuItemHook):
    def __init__(self):
        super().__init__(
            _('Skyhook Monitor'),
            'fas fa-satellite fa-fw',
            'aa_skyhook_monitor:index',
            9999,
            navactive=['aa_skyhook_monitor:'],
        )

    def render(self, request):
        if request.user.has_perm('aa_skyhook_monitor.view_skyhooks'):
            return MenuItemHook.render(self, request)
        return ''


@hooks.register('menu_item_hook')
def register_menu():
    return SkyhookMenuItemHook()


@hooks.register('url_hook')
def register_urls():
    return UrlHook(aa_skyhook_monitor.urls, 'aa_skyhook_monitor', r'^skyhook/')
