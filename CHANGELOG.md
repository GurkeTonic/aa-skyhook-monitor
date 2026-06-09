# Changelog

## [0.1.3] - 2026-06-09

### Added
- `pyproject.toml` (hatchling) als alleinige Packaging-Konfiguration
- `app_settings.py` für konfigurierbare Task-Timeouts und Warning-Minuten
- `constants.py` für ESI-Basis-URL, Reagent- und Planeten-Type-IDs sowie Bay-Volumen
- `managers.py` mit `SkyhookManager` für Query-Optimierungen
- `models/` als Package (ersetzt `models.py`)
- Static Files und erweiterte Templates (base, bundles, partials)
- `.github/` Workflow-Konfiguration
- `runtests.py` und `tests/`-Verzeichnis

### Changed
- ESI `_esi_get()`: X-Pages Pagination — alle Seiten werden jetzt abgerufen
- `auth_hooks.py`: `navactive` ergänzt (aktives Nav-Highlighting), Label mit `gettext_lazy`
- `pyproject.toml`: `requires-python` auf `>=3.10,<3.14` eingeschränkt

### Removed
- `setup.cfg` (durch `pyproject.toml` ersetzt)

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
