# Changelog

## [0.2.0] - 2026-06-12

### Added

- Single global "last sync" timestamp in the list view
- i18n support (English source, German translation)
- Standalone test project (`testauth/`) and task tests
- Discord webhook retry with `429 Retry-After` handling
- Dev tooling: pre-commit, tox, Makefile, flake8, editorconfig

### Changed

- ESI access switched to the django-esi OpenAPI client (caching, ETags, rate limiting)
- Retry ESI tasks on rate/error limits, skip on `304 Not Modified`
- Periodic tasks run under `QueueOnce`
- Menu order set to `9999`
- README aligned with code (GPL-3.0, Python ≥ 3.10, django-esi ≥ 4)

### Fixed

- Stale-skyhook pruning no longer deletes other owners' skyhooks
- Admin "Ping Test" reuses the shared Discord sender

### Removed

- `setup.py`, unused `ESI_BASE` constant

## [0.1.3] - 2026-06-09

### Added

- `pyproject.toml` (hatchling) as sole packaging config
- `app_settings.py`, `constants.py`, `managers.py`
- `models/` package, extended templates, static files
- `runtests.py` and test suite

### Changed

- ESI listing: X-Pages pagination (fetch all pages)
- `requires-python` set to `>=3.10,<3.14`

### Removed

- `setup.cfg`

## [0.1.0] - 2026-06-08

### Added

- Initial release: per-corp Skyhook bay contents with m³ progress bars
- Theft-vulnerability window with local-time countdown
- Discord notifications (30-min warning, vulnerability start)
- Permissions `view_skyhooks` / `manage_skyhooks`
- Hourly Celery sync + 5-minute notification checks
