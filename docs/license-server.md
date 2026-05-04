# IronMail License Server

## Runtime

- Public domain: `https://tmpmail.oldiron.us`
- Backend listener: `127.0.0.1:18081`
- Process manager: `systemd`
- Reverse proxy and TLS: existing `nginx`
- Database: SQLite at `/opt/ironmail-license/data/licenses.sqlite3`

## Environment

The production service reads `/etc/ironmail-license.env`.

Required variables:

- `IRONMAIL_ADMIN_USERNAME`
- `IRONMAIL_ADMIN_PASSWORD`
- `IRONMAIL_SESSION_SECRET`
- `IRONMAIL_DATA_DIR`
- `IRONMAIL_DATABASE_PATH`

## API

`POST /api/v1/licenses/verify`

Request:

```json
{
  "code": "IM-XXXXXX-XXXXXX-XXXXXX-XXXXXX",
  "device_id": "sha256-device-id",
  "app_version": "1.0.0"
}
```

Successful response:

```json
{
  "valid": true,
  "reason": "ok",
  "expires_at": null,
  "device_bound": true
}
```

Failure reasons include `missing_code`, `not_found`, `disabled`, `expired`, and `device_mismatch`.

## Admin

Open `https://tmpmail.oldiron.us/admin/login`.

The admin UI supports creating, listing, updating, disabling, deleting, and unbinding license codes. Full license codes are only shown once after creation. The database stores only hashed codes plus a short prefix.
