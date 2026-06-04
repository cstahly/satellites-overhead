# Mobile API handoff

Last updated: June 4, 2026

This is the backend foundation for an iPhone-first, Android-compatible SDR
companion app. It does not send APNs or FCM pushes yet; it provides the stable
API, device registry, event stream, and pending notification outbox that a push
worker and mobile client will consume.

## Agent pickup status

As of the last edit on June 4, 2026, the backend foundation is live:

- Functional code is committed:
  - `d6e58d4 Add bearer-authenticated mobile API runtime`
  - `b5f3bf4 Emit scheduler lifecycle events`
  - `f872f1b Document mobile API deployment and rollback`
- The functional code has passed `python3 -m unittest discover -v` (13 tests)
  and Python compilation.
- The live web and scheduler services have been restarted and verified.
- The public nginx `/api/v1` bearer-auth split is installed and verified.
- Initial full-scope token `tok_7c9873925e18470c` is active. Its one-time raw
  secret is temporarily stored at `~/sdr_mobile_bootstrap_token.json`, mode
  `0600`. Give it only to the owner/app, then delete that temporary file.
- A deployment read-only token was created, scope-tested, and revoked.
- Device registration/redaction/removal was tested; the live device list is
  empty after cleanup.
- `.tlecache/active.tle` is runtime churn and must not be committed or reverted.

Next implementation work:

1. Scaffold the iOS/Android app against `/api/v1`; use the event stream for
   foreground updates and device registration for push enrollment.
2. Implement a push-delivery worker that consumes
   `~/sdr_notification_outbox.jsonl`, respects device preferences, and records
   delivery outcomes without blocking the scheduler.
3. Add a narrowly scoped remote Claude-invocation API only after defining its
   prompts, allowed context/actions, audit records, and concurrency behavior.

Deployment record:

- Initial token id: `tok_7c9873925e18470c`
- Temporary raw-token handoff: `~/sdr_mobile_bootstrap_token.json` (`0600`)
- EC2 nginx backup:
  `/etc/nginx/conf.d/sdr.conf.before-mobile-api-20260604T044109Z`
- Live web restart: complete
- Live scheduler restart: complete
- Public nginx reload: complete
- Verified: public `/` and `/api/v1foo` use Basic Auth; `/api/v1` uses Bearer;
  bearer status/events return `200`; revoked token returns `401`; insufficient
  scope returns `403`; private tunnel and portfolio remain healthy.

## Boundaries

- The scheduler remains the only process that runs HackRF or SatDump.
- The scheduler does not call or depend on the web server, nginx, tunnel, or
  internet. It appends events directly to a local JSONL file and continues if
  that write fails.
- Legacy web routes remain unchanged and are protected publicly by nginx Basic
  Auth.
- Every `/api/v1` request is authenticated by `serve.py` with a revocable
  bearer token. There is no loopback authentication bypass because public
  tunnel traffic reaches the app through loopback.
- Remote `control` tokens can add/update/delete rules and queue immediate
  captures without an approval prompt.

## Runtime files

All files are under the service user's home directory and are mode `0600`.
They are runtime state and must not be committed.

| File | Purpose |
|------|---------|
| `~/sdr_api_tokens.json` | Token metadata and SHA-256 hashes; never raw secrets |
| `~/sdr_scheduler_events.jsonl` | Append-only web/scheduler event stream |
| `~/sdr_mobile_devices.json` | APNs/FCM device tokens; API responses redact them |
| `~/sdr_notification_outbox.jsonl` | Pending notification records for a future sender |

Associated `*.lock` files serialize updates between the CLI, threaded web
server, and scheduler.

`~/sdr_mobile_bootstrap_token.json` is a temporary mode-`0600` handoff
containing the initial raw secret. It is not used by the services and should be
deleted after the app/owner stores the token.

## Token operations

Create the initial or replacement token locally:

```bash
python3 manage_api_tokens.py create --name mobile-bootstrap
python3 manage_api_tokens.py create --name read-only --scope read
python3 manage_api_tokens.py list
python3 manage_api_tokens.py revoke tok_ID
```

The raw bearer token is printed only by `create`. The stored file contains its
hash, so losing the raw token requires creating a replacement. Available
scopes:

- `read`: status, rules, passes, captures, events, notifications, and metadata
- `control`: all non-token/device mutations; also grants read access
- `devices:manage`: register, list, and remove push devices
- `tokens:manage`: create, list, and revoke bearer tokens
- `*`: all scopes

Use a token:

```bash
curl -H "Authorization: Bearer $SDR_TOKEN" \
  https://sdr.sadbabyrabbit.com/api/v1/status
```

## Mobile endpoints

| Method | Path | Scope | Purpose |
|--------|------|-------|---------|
| `GET` | `/api/v1` | `read` | Endpoint index |
| `GET` | `/api/v1/events?after=ID&limit=100` | `read` | Recent scheduler/web events |
| `GET` | `/api/v1/notifications?status=pending` | `read` | Notification outbox inspection |
| `GET` | `/api/v1/devices` | `devices:manage` | List redacted device records |
| `POST` | `/api/v1/devices` | `devices:manage` | Register/update an iOS or Android device |
| `DELETE` | `/api/v1/devices/ID` | `devices:manage` | Remove a device |
| `GET` | `/api/v1/tokens` | `tokens:manage` | List redacted token metadata |
| `POST` | `/api/v1/tokens` | `tokens:manage` | Create a token; secret returned once |
| `DELETE` | `/api/v1/tokens/ID` | `tokens:manage` | Revoke a token immediately |

The existing versioned scheduler, pass, satellite, and capture endpoints remain
listed by `GET /api/v1`.

Example device registration:

```json
{
  "name": "Chris iPhone",
  "platform": "ios",
  "push_token": "APNS_OR_PROVIDER_TOKEN",
  "enabled": true,
  "preferences": {
    "capture.started": true,
    "capture.completed": true,
    "capture.failed": true
  }
}
```

## Event types

The web API emits rule, scan, device, and token mutation events. The scheduler
emits:

- `scheduler.started`
- `schedule.changed`
- `capture.started`
- `capture.completed`
- `capture.failed`
- `monitor.result`
- `capture.retry_queued`
- `claude.invoked`

Capture lifecycle and intervention events also append a pending notification
record. A later push worker will deliver those records and update delivery
state; no delivery process exists yet.

## Public nginx split

`deploy/nginx-sdr.conf` keeps Basic Auth on `/` and disables Basic Auth only for
the exact `/api/v1` path and `/api/v1/` subtree. `serve.py` then enforces bearer
auth. This split is live; the pre-deployment nginx backup is recorded above.

## Rollback

Code rollback:

```bash
git revert b5f3bf4 d6e58d4
systemctl --user restart satellites-overhead.service
# Restart sdr-scheduler.service only outside a pass window.
```

Public-route rollback:

```bash
ssh sadbabyrabbit.com
sudo cp -a /etc/nginx/conf.d/sdr.conf.before-mobile-api-20260604T044109Z \
  /etc/nginx/conf.d/sdr.conf
sudo nginx -t
sudo systemctl reload nginx
```

That returns `/api/v1` to Basic Auth without affecting the scheduler.

Runtime files can be retained through rollback. To fully remove the mobile
state, move the four runtime files and their `*.lock` files to a private backup
directory after stopping the web and scheduler services.
