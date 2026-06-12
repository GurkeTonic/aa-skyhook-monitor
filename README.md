# AA Skyhook Monitor

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org/)
[![Alliance Auth](https://img.shields.io/badge/alliance--auth-5.1+-orange)](https://gitlab.com/allianceauth/allianceauth)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

An [Alliance Auth](https://gitlab.com/allianceauth/allianceauth) plugin to monitor Skyhook bay contents per corporation via ESI, with Discord webhook notifications for vulnerability windows.

---

## Features

- Lists all active Skyhooks with **Magmatic Gas** and **Superionic Ice** reagent contents
- Displays **Secured Bay** and **Unsecured Bay** stock with m³ capacity progress bars
- Shows **Theft Vulnerability** start time in local browser time with live second-by-second countdown
- Table sorted by next upcoming vulnerability window — active windows first, expired last
- Only Lava and Ice planet Skyhooks are tracked — irrelevant structures filtered out via EVE SDE
- **Discord Webhook Notifications**
  - ⏰ @here ping 30 minutes before vulnerability starts
  - 🚨 @everyone ping when vulnerability window opens
  - Compact embed format with corp, planet, timer and reagent contents in one message
- Automatic hourly Celery Beat sync — no manual `local.py` configuration required
- ESI response cache respected (1 hour TTL); expired vulnerability windows trigger an immediate cache bypass to pick up new schedules
- Manual sync trigger and **Ping Test** action via Django Admin
- Planet and type names resolved from local EVE SDE — no extra ESI calls needed

---

## Requirements

| Requirement | Version |
|---|---|
| Alliance Auth | >= 5.1.0 |
| Python | >= 3.10 |
| django-esi | >= 4 |
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

To verify the webhook is working, select the configuration in Django Admin and run the **Ping Test** action — it sends both embed variants with real data from the database.

---

## Permissions

| Permission | Description |
|---|---|
| `view_skyhooks` | Can view Skyhook bay contents |
| `manage_skyhooks` | Can add and remove corporations |

Assign permissions via **Django Admin → Auth → Groups**.

---

## Admin

### Skyhook Owners

Select one or more owners and run **"Jetzt von ESI aktualisieren"** to trigger an immediate sync outside of the hourly schedule.

### Skyhook Monitor Konfiguration

| Action | Description |
|---|---|
| Ping Test | Sends both warning and active embed to the configured webhook using real database values |
| Löschen | Removes the configuration |

---

## Technical Notes

- Only **Lava** (type 2015) and **Ice** (type 12) planet Skyhooks are fetched — determined via SDE before any ESI detail calls are made, reducing API usage from ~100+ to ~18 calls per sync
- ESI detail endpoint cache TTL is 1 hour (`Cache-Control: max-age=3600`); when a vulnerability window has ended the cache entry is invalidated so the next task run picks up the new schedule immediately
- Detail calls are rate-limited to 15/minute
- Bay volume: 10,468 m³ per bay (secured and unsecured each)
- Celery Beat schedules register automatically on app startup — no `CELERYBEAT_SCHEDULE` entries in `local.py` needed
- Vulnerability countdown runs in the browser in the user's local timezone; page auto-reloads every 5 minutes to pick up task-updated data

---

## Contributing

Pull requests are welcome. For major changes please open an issue first.

---

## License

[GPL-3.0-or-later](LICENSE)
