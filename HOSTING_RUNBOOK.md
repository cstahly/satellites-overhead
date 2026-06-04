# Hosted web deployment runbook

Last audited: June 3, 2026

This file documents the hosted-web deployment so another agent can understand,
verify, and undo it without guessing.

## Safety rules

- The SDR scheduler remains authoritative for hardware.
- Do not restart `sdr-scheduler.service` during or near a pass.
- Do not expose port `8723` directly to the internet.
- Do not publish the current unauthenticated API without an nginx auth boundary.
- Preserve the existing portfolio at `https://sadbabyrabbit.com`.
- Do not commit passwords, private keys, certificates, or generated auth files.

## Audited starting state

Kali:

- Local web service: `satellites-overhead.service`
- Local URL: `http://127.0.0.1:8723`
- Scheduler service: `sdr-scheduler.service`
- Existing SSH host alias: `sadbabyrabbit.com`
- Existing SSH identity: `~/.ssh/sadbabyrabbit.pem`

Public EC2 host:

- Host: `sadbabyrabbit.com` / `3.148.96.123`
- OS: Amazon Linux 2023
- nginx serves the existing Next.js portfolio
- Next.js listens on public-host loopback port `3000`
- SSH TCP forwarding is enabled
- SSH `GatewayPorts` is disabled, so remote forwards bind to loopback only
- nginx configuration: `/etc/nginx/conf.d/site.conf`
- Existing TLS files: `/etc/nginx/ssl/sadbabyrabbit.com/`
- DNS is managed by Namecheap, not Cloudflare

No Cloudflare Tunnel or Tailscale installation existed at audit time.

## Deployment status

Installed and verified on June 3/4, 2026:

- Baseline git tag: `pre-public-web-20260603`
- Kali user service: `sdr-web-tunnel.service`
- EC2 loopback listener: `127.0.0.1:18723`
- EC2 can fetch `http://127.0.0.1:18723/scheduler/status`
- Existing portfolio remains unchanged
- Authenticated HTTP bootstrap route installed on EC2:
  `/etc/nginx/conf.d/sdr.conf`
- HTTP Basic Auth hash installed on EC2: `/etc/nginx/sdr.htpasswd`
- nginx backup before bootstrap route:
  `/etc/nginx/conf.d.backup-sdr-20260604030313`
- Unauthenticated bootstrap requests return `401`
- Authenticated bootstrap requests reach the SDR app
- Namecheap DNS: `sdr.sadbabyrabbit.com A 3.148.96.123`
- Let's Encrypt certificate installed:
  `/etc/nginx/ssl/sdr.sadbabyrabbit.com/`
- Certificate renewal reloads nginx through acme.sh
- HTTP redirects to HTTPS
- HTTPS unauthenticated requests return `401`
- HTTPS authenticated requests reach the SDR app
- HTTP bootstrap nginx backup:
  `/etc/nginx/conf.d/sdr.conf.bootstrap-20260604`
- nginx backup before authenticated-user forwarding:
  `/etc/nginx/conf.d/sdr.conf.before-api-20260604031457`
- Password-file backup before repairing a missing username prefix:
  `/etc/nginx/sdr.htpasswd.missing-user-20260604041550`
- Public URL: `https://sdr.sadbabyrabbit.com`
- Versioned API index: `https://sdr.sadbabyrabbit.com/api/v1`
- Mutation audit log on Kali: `~/sdr_web_audit.jsonl`
- Application bearer auth is live for `/api/v1`
- Basic Auth remains live for `/` and legacy browser routes
- nginx backup before the `/api/v1` bearer split:
  `/etc/nginx/conf.d/sdr.conf.before-mobile-api-20260604T044109Z`
- Initial mobile API token id: `tok_7c9873925e18470c`
- Temporary mode-`0600` raw-token handoff:
  `~/sdr_mobile_bootstrap_token.json` on Kali; delete after app provisioning

## Selected transport

Use a reverse SSH tunnel initiated by Kali:

```text
EC2 127.0.0.1:18723 -> SSH tunnel -> Kali 127.0.0.1:8723
```

This keeps the scheduler/web API behind an outbound connection. EC2 port 18723
is not publicly reachable. nginx is the only public entry point.

The user service template is:

```text
deploy/sdr-web-tunnel.service
```

## Public placement decision required

Confirmed by owner:

- Public hostname: `sdr.sadbabyrabbit.com`
- HTTP Basic Auth username: `cstahly`

The generated password is not stored in this repository. Only its password hash
is installed at `/etc/nginx/sdr.htpasswd` on EC2.

## Install and verify the private tunnel

Installing the tunnel does not expose the app publicly:

```bash
install -m 0644 deploy/sdr-web-tunnel.service \
  ~/.config/systemd/user/sdr-web-tunnel.service
systemctl --user daemon-reload
systemctl --user enable --now sdr-web-tunnel.service
systemctl --user status sdr-web-tunnel.service
```

Verify from EC2:

```bash
ssh sadbabyrabbit.com 'curl -fsS http://127.0.0.1:18723/scheduler/status'
```

## Public nginx deployment

1. Create this Namecheap DNS record:

   ```text
   Type: A Record
   Host: sdr
   Value: 3.148.96.123
   TTL: Automatic
   ```

2. Issue a TLS certificate for the selected hostname.
3. Create an htpasswd file on EC2.
4. Install the checked-in final configuration:

   ```text
   deploy/nginx-sdr.conf
   ```

   The generic template remains at `deploy/nginx-sdr.conf.template`.
5. Back up nginx configuration before installing:

   ```bash
   ssh sadbabyrabbit.com \
     'sudo cp -a /etc/nginx/conf.d /etc/nginx/conf.d.backup-$(date +%Y%m%d%H%M%S)'
   ```

6. Test before reload:

   ```bash
   ssh sadbabyrabbit.com 'sudo nginx -t'
   ```

7. Reload nginx, never restart it for this deployment:

   ```bash
   ssh sadbabyrabbit.com 'sudo systemctl reload nginx'
   ```

## Authentication boundary

The browser frontend and legacy routes use nginx HTTP Basic Auth. The
`/api/v1` subtree uses revocable bearer credentials enforced by `serve.py`;
nginx disables Basic Auth only for exact `/api/v1` and `/api/v1/` paths and
forwards the `Authorization` header. Never add a loopback bypass in `serve.py`,
because reverse-tunnel requests arrive on loopback.

nginx forwards the authenticated username to the app as `X-Remote-User`.
Rule upserts/deletes and queued immediate scans are appended to
`~/sdr_web_audit.jsonl`. Audit write failure is logged but does not prevent a
scheduler command from being accepted.

Create/revoke application tokens locally with `manage_api_tokens.py`. Token
secrets are printed once and only SHA-256 hashes are stored in
`~/sdr_api_tokens.json`. See `MOBILE_API_HANDOFF.md` for scopes and endpoints.

### Rotate the Basic Auth password

Run this interactively on the EC2 host. The password file must contain both the
username and hash in the form `cstahly:$6$...`; a hash without the username
causes nginx to report that the user does not exist.

```bash
ssh sadbabyrabbit.com
sudo cp -a /etc/nginx/sdr.htpasswd \
  /etc/nginx/sdr.htpasswd.backup-$(date +%Y%m%d%H%M%S)
read -rsp "New password: " PASS; echo
HASH=$(printf '%s' "$PASS" | openssl passwd -6 -stdin)
unset PASS
printf '%s:%s\n' cstahly "$HASH" | sudo tee /etc/nginx/sdr.htpasswd >/dev/null
unset HASH
sudo chown root:nginx /etc/nginx/sdr.htpasswd
sudo chmod 0640 /etc/nginx/sdr.htpasswd
sudo restorecon /etc/nginx/sdr.htpasswd
sudo awk -F: 'NF == 2 && $1 == "cstahly" && $2 ~ /^\$6\$/ {ok=1} END {exit !ok}' \
  /etc/nginx/sdr.htpasswd
```

No nginx reload is required. Browsers may cache old Basic Auth credentials; use
a private window if the browser does not prompt for the new password.

## Rollback

Disable the private tunnel:

```bash
systemctl --user disable --now sdr-web-tunnel.service
rm ~/.config/systemd/user/sdr-web-tunnel.service
systemctl --user daemon-reload
```

Remove the public route:

```bash
ssh sadbabyrabbit.com
sudo rm /etc/nginx/conf.d/sdr.conf
sudo nginx -t
sudo systemctl reload nginx
```

Then remove the selected DNS record. These actions do not change or stop the
local web service or scheduler.

## Verification checklist

```bash
# Local services remain healthy
systemctl --user is-active satellites-overhead.service
systemctl --user is-active sdr-scheduler.service
curl -fsS http://127.0.0.1:8723/scheduler/status

# Tunnel is private and healthy
systemctl --user is-active sdr-web-tunnel.service
ssh sadbabyrabbit.com 'curl -fsS http://127.0.0.1:18723/scheduler/status'

# Public site remains healthy
curl -fsSIL https://sadbabyrabbit.com

# Public SDR hostname must reject unauthenticated requests
curl -sS -o /dev/null -w '%{http_code}\n' "https://SELECTED_HOSTNAME/"
# Expected: 401
```
