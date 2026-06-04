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

Installed and verified on June 3, 2026:

- Baseline git tag: `pre-public-web-20260603`
- Kali user service: `sdr-web-tunnel.service`
- EC2 loopback listener: `127.0.0.1:18723`
- EC2 can fetch `http://127.0.0.1:18723/scheduler/status`
- Existing portfolio remains unchanged
- No public SDR DNS record or nginx route has been installed yet

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

Before configuring nginx or DNS, the owner must select the public hostname.

Recommended:

```text
sdr.sadbabyrabbit.com
```

This preserves the existing portfolio and avoids path-prefix problems in the
single-file frontend. Do not assume the hostname without owner confirmation.

The owner must also select the HTTP Basic Auth username. A password can be
generated locally and stored only in nginx's htpasswd file.

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

Do this only after the owner confirms the hostname and auth username.

1. Create the selected Namecheap DNS record pointing to `3.148.96.123`.
2. Issue a TLS certificate for the selected hostname.
3. Create an htpasswd file on EC2.
4. Render `deploy/nginx-sdr.conf.template` with the selected hostname and cert
   paths.
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

The initial public deployment uses nginx HTTP Basic Auth for every route. This
works with the current browser app because frontend and API remain same-origin.

The later mobile API should use revocable bearer credentials or an identity
provider. Do not remove Basic Auth until the application API enforces its own
authentication and authorization.

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
