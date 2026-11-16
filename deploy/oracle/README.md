# Oracle deployment

The repository belongs at `/home/ubuntu/safrano9999/JUGO`.
Run `python3 deploy/oracle/setup.py` as `ubuntu` to create missing runtime files,
persistent directories and a Quadlet symlink under `~/.config/containers/systemd`.
Existing `.env` and `config.conf` files are preserved. The Quadlet is rendered
from `deployment.json`; `container.conf` records its image/network/port settings.

Builds and container checks run only on GitHub Actions, using recipes from
`SCRIPTS/githubactions/JUGO`. Pull the published image explicitly with
`podman pull ghcr.io/safrano9999/jugo:latest` on Oracle, then run
`systemctl --user daemon-reload` and `systemctl --user start jugo.service`.
The Quadlet uses `Pull=never` and does not publish a backend port on the host.

Connect the included Caddy block to the existing `litellm-free-caddy` container
on `litellm-free_default`. Publish only `127.0.0.1:6009:6009`
on Caddy. Register that frontend in Citadel with the existing email Access policy.
The intended hostname is `jugo.f24-sales.com` and the Tailscale URL is
`https://litellm.tailbab54f.ts.net:6009`.

LLM provider credentials are pending. The UI starts without them. Later configure
the intended gateway and its application key in `.env`; do not use a placeholder
key or copy the gateway's master key into applications.

NaturalGrounding's setup generates its Django secret and bootstrap admin password
only when `.env` is absent. Credentials stay in that private file on Oracle.
