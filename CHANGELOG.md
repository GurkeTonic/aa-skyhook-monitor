# Changelog

## [0.1.0] - 2026-06-08

### Added
- Initial release
- Display Skyhook bay contents (secured/unsecured stock) per corporation
- Progress bars showing bay fill level in m³
- Theft vulnerability window display with local-time countdown
- Discord webhook notifications: 30min warning (@here) and vulnerability start (@everyone)
- Permission system: `view_skyhooks` and `manage_skyhooks`
- Celery Beat tasks for automatic hourly sync and 5-minute notification checks
- Django Admin configuration for Discord webhook URL
