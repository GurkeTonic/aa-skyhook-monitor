from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook
import aa_skyhook_monitor.urls


@hooks.register('menu_item_hook')
def register_menu():
    return MenuItemHook(
        'Skyhook Monitor',
        'fas fa-satellite fa-fw',
        'aa_skyhook_monitor:index',
        150
    )


@hooks.register('url_hook')
def register_urls():
    return UrlHook(aa_skyhook_monitor.urls, 'aa_skyhook_monitor', r'^skyhook/')
