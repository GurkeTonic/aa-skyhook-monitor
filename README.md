# AA Skyhook Monitor

[![Python](https://img.shields.io/badge/python-3.8+-blue)](https://www.python.org/)
[![Alliance Auth](https://img.shields.io/badge/alliance--auth-5.1+-orange)](https://gitlab.com/allianceauth/allianceauth)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An [Alliance Auth](https://gitlab.com/allianceauth/allianceauth) plugin to monitor Skyhook bay contents per corporation via ESI, with Discord webhook notifications for vulnerability windows.

---

## Features

- Lists all active Skyhooks with reagent bay contents per corporation
- Displays **Secured Bay** and **Unsecured Bay** stock with m³ capacity progress bars
- Shows **Theft Vulnerability** start time in local browser time with live countdown
- Status badge — live calculation whether a Skyhook is currently vulnerable
- Table sorted by next upcoming vulnerability window
- **Discord Webhook Notifications**
  - @here ping 30 minutes before vulnerability starts
  - @everyone ping when vulnerability window opens
- Automatic hourly Celery Beat sync — no manual `local.py` configuration required
- Manual sync trigger via Django Admin
- Planet and type names resolved from local EVE SDE
- Role-based access control via Alliance Auth permissions

---

## Requirements

| Requirement | Version |
|---|---|
| Alliance Auth | >= 5.1.0 |
| Python | >= 3.8 |
| [django-eveonline-sde](https://github.com/nicoscha/django-eveonline-sde) | latest |

### ESI Scope

| Scope | Endpoint |
|---|---|
| `esi-structures.read_corporation.v1` | Skyhook list and bay details |

> The character used to authorize a corporation must have the in-game **Station Manager** role.

---

## Installation

**Step 1 — Install the package**

    pip install git+https://github.com/GurkeTonic/aa-skyhook-monitor.git

**Step 2 — Install EVE SDE (if not already present)**

    pip install django-eveonline-sde

**Step 3 — Add to `INSTALLED_APPS` in `local.py`**

    INSTALLED_APPS += [
        'aa_skyhook_monitor',
        'eve_sde',
    ]

**Step 4 — Run migrations and collect static**

    python manage.py migrate
    python manage.py collectstatic

**Step 5 — Load SDE data**

    python manage.py import_sde

**Step 6 — Restart services**

    sudo supervisorctl restart myauth:

---

## Setup

1. Open **Skyhook Monitor** in the Alliance Auth navigation menu
2. Click **+ Corp hinzufügen** and authenticate with a character that has the **Station Manager** role in the target corporation
3. The first automatic sync runs within the hour, or trigger it manually via Django Admin

---

## Discord Notifications (optional)

1. Create a Webhook in your Discord server (Channel Settings → Integrations → Webhooks)
2. Go to **Django Admin → Skyhook Monitor → Skyhook Monitor Konfiguration → Add**
3. Enter the Webhook URL and save

| Notification | Trigger | Mention |
|---|---|---|
| ⏰ Warning ping | 30 minutes before vuln start | @here |
| 🚨 Active ping | When vuln window opens | @everyone |

---

## Permissions

| Permission | Description |
|---|---|
| `view_skyhooks` | Can view Skyhook bay contents |
| `manage_skyhooks` | Can add and remove corporations |

Assign permissions via **Django Admin → Auth → Groups**.

---

## Admin

Go to **Django Admin → Skyhook Monitor → Skyhook Owners**, select corporations and run the action **"Jetzt von ESI aktualisieren"** to trigger an immediate sync.

---

## Technical Notes

- ESI endpoint requires header `X-Compatibility-Date: 2026-05-19`
- Detail calls are rate-limited to 15/minute to stay within ESI's `corp-structure` limit (300 per 15 minutes)
- Bay volume: 10,468 m³ per bay (secured and unsecured each)
- Celery Beat schedules register automatically on app startup — no `CELERYBEAT_SCHEDULE` entries in `local.py` needed
- Vulnerability countdown runs in the browser — displayed in the user's local timezone

---

## Contributing

Pull requests are welcome. For major changes please open an issue first.

---

## License

[MIT](LICENSE)
