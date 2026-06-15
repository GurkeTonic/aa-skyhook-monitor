# AA Skyhook Monitor

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org/)
[![Alliance Auth](https://img.shields.io/badge/alliance--auth-5.1+-orange)](https://gitlab.com/allianceauth/allianceauth)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

An [Alliance Auth](https://gitlab.com/allianceauth/allianceauth) plugin to monitor Skyhook bay contents per corporation via ESI, with Discord webhook notifications for vulnerability windows. Also tracks publicly raidable Skyhooks across New Eden with optional region/constellation filtering and Discord alerts.

______________________________________________________________________

## Features

### My Skyhooks (per corporation)

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
- Manual sync trigger and **Ping Test** action via Django Admin

### Raidable Skyhooks (public feed)

- Lists all currently raidable Skyhooks across New Eden from the public ESI feed
- Refreshed every 5 minutes, no ESI token required
- Filter by **region** and **constellation** (configured via admin dual-list)
- **Discord Webhook Notifications** — alerts fire only for new entries, no duplicate pings after server restarts
- Admin read-only view for inspecting raidable entries and notification state

______________________________________________________________________

## Requirements

| Requirement                                                              | Version  |
| ------------------------------------------------------------------------ | -------- |
| Alliance Auth                                                            | >= 5.1.0 |
| Python                                                                   | >= 3.10  |
| django-esi                                                               | >= 4     |
| [django-eveonline-sde](https://github.com/nicoscha/django-eveonline-sde) | latest   |

### ESI Scope

| Scope                                | Endpoint                     |
| ------------------------------------ | ---------------------------- |
| `esi-structures.read_corporation.v1` | Skyhook list and bay details |

> The character used to authorize a corporation must have the in-game **Station Manager** role.
>
> The raidable feed uses a public ESI endpoint — no scope or token needed.

______________________________________________________________________

## Installation

**Step 1 — Install the package**

```
pip install git+https://github.com/GurkeTonic/aa-skyhook-monitor.git
```

**Step 2 — Install EVE SDE (if not already present)**

```
pip install django-eveonline-sde
```

**Step 3 — Add to `INSTALLED_APPS` in `local.py`**

```
INSTALLED_APPS += [
    'aa_skyhook_monitor',
    'eve_sde',
]
```

**Step 4 — Add your contact email to `local.py` (required by CCP)**

```
ESI_USER_CONTACT_EMAIL = "you@example.com"
```

**Step 5 — Run migrations and collect static**

```
python manage.py migrate
python manage.py collectstatic
```

**Step 6 — Load SDE data**

```
python manage.py esde_load_sde
```

**Step 7 — Restart services**

```
sudo supervisorctl restart myauth:
```

______________________________________________________________________

## Setup

1. Open **Skyhook Monitor** in the Alliance Auth navigation menu
1. Click **+ Corp hinzufügen** and authenticate with a character that has the **Station Manager** role in the target corporation
1. The first automatic sync runs within the hour, or trigger it manually via Django Admin

______________________________________________________________________

## Discord Notifications (optional)

### My Skyhooks

1. Create a Webhook in your Discord server (Channel Settings → Integrations → Webhooks)
1. Go to **Django Admin → Skyhook Monitor → Skyhook Monitor Konfiguration → Add**
1. Enter the Webhook URL in the **Discord Webhook URL** field and save

| Notification    | Trigger                      | Mention   |
| --------------- | ---------------------------- | --------- |
| ⏰ Warning ping | 30 minutes before vuln start | @here     |
| 🚨 Active ping  | When vuln window opens       | @everyone |

To verify the webhook is working, select the configuration in Django Admin and run the **Ping Test** action.

### Raidable Skyhooks

1. Enter a second Webhook URL in the **Raidable Webhook URL** field of the same configuration
1. Optionally select **Watched Regions** and/or **Watched Constellations** to limit which alerts fire
1. Alerts are sent once per raidable entry — the `notified` flag persists across restarts

______________________________________________________________________

## Permissions

| Permission        | Description                                         |
| ----------------- | --------------------------------------------------- |
| `view_skyhooks`   | Can view Skyhook bay contents and the raidable feed |
| `manage_skyhooks` | Can add and remove corporations                     |

Assign permissions via **Django Admin → Auth → Groups**.

______________________________________________________________________

## Admin

### Skyhook Owners

Select one or more owners and run **"Update from ESI now"** to trigger an immediate sync outside of the hourly schedule.

### Raidable Skyhook List

Read-only inspection view showing all entries currently in the database with their `notified` state. Useful for verifying filter results and debugging Discord alerts.

### Skyhook Monitor Konfiguration

| Action    | Description                                                                              |
| --------- | ---------------------------------------------------------------------------------------- |
| Ping Test | Sends both warning and active embed to the configured webhook using real database values |
| Delete    | Removes the configuration                                                                |

Use the **Watched Regions** and **Watched Constellations** dual-list to restrict raidable alerts to specific areas. Leave both empty to receive alerts for all raidable Skyhooks.

______________________________________________________________________

## Technical Notes

- Only **Lava** (type 2015) and **Ice** (type 12) planet Skyhooks are fetched — determined via SDE before any ESI detail calls, reducing API usage from ~100+ to ~18 calls per sync
- ESI detail endpoint cache is event-based (TTL 1 hour); expired vulnerability windows trigger an immediate cache bypass to pick up new schedules
- Detail calls are rate-limited to 15/minute; raidable feed uses rate-limit group `activity` (30 calls / 15 min)
- Bay volume: 10,468 m³ per bay (secured and unsecured each)
- Region/constellation filter options are auto-populated from the SDE on each raidable sync — no manual setup needed
- Celery Beat schedules register automatically on app startup — no `CELERYBEAT_SCHEDULE` entries in `local.py` needed
- Vulnerability countdown runs in the browser in the user's local timezone; page auto-reloads every 5 minutes

______________________________________________________________________

## Contributing

Pull requests are welcome. For major changes please open an issue first.

______________________________________________________________________

## License

[GPL-3.0-or-later](LICENSE)
