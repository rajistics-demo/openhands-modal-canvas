# Set up the Modal Enterprise Canvas pilot

Use an isolated [Enterprise 1.88.0 Compose install](https://github.com/OpenHands/enterprise/blob/c6191be/README.md#run-locally-with-docker-compose)
with Compose 2.24.4 or later. Verify a stock conversation before switching.
The pilot uses Sandbox V1 and the original Enterprise conversation URL. The
dedicated Pause button and embedded preview require the provider-aware Canvas
build used in the evaluation. Stock Sandbox V1 can exercise pause and resume
through the API.

## 1. Prepare Modal and DNS

Select an existing app in a Modal workspace that can create Linux VMs and use
memory snapshots. The adapter uses Modal SDK 1.6.0 and looks up that app without
creating one. Put a dedicated profile with only the credential authorized for
this test in a protected TOML file. Use an isolated environment or a
[scoped service user](https://modal.com/docs/guide/service-users) where available.
The AWS test used a separate Compose host. Compose itself can run anywhere that
can reach Modal and receive guest callbacks.

Pick one DNS-safe sandbox ID of at most 63 characters and create three DNS
records for `WEB_HOST`, the dedicated runtime hostname, and
`<sandbox-id>.preview.<WEB_HOST>`. Point them at the Compose HTTPS listener.
Use a TLS origin that runs Canvas and the Enterprise application, with no
path in `WEB_URL`, and set `AGENT_CANVAS_LOCK_TO_CLOUD` to that URL. The sample
edge permits event callbacks and restricts browser and preview access to
`MODAL_OPERATOR_CIDR`.

Create a random preview signing key with `openssl rand -hex 48`. Put it and the
Modal profile outside the checkout. The mounted files must be readable by
the Enterprise image's `openhands` UID/GID 42420. Use protected directories
and restrictive permissions.

## 2. Build and start

Run these commands at the repository root and then in the isolated install
directory. The overlay adds nullable provider mapping columns to the local
Enterprise database. Preserve its volumes and the original Compose file list.

```bash
docker build -f enterprise-pilot/Dockerfile -t local/modal-enterprise:1.88.0 enterprise-pilot
export MODAL_PACKAGE="$PWD"
cd "$ISOLATED_COMPOSE_DIR"
cp "$MODAL_PACKAGE/compose/modal.env.example" modal.env
chmod 600 modal.env
# Fill in modal.env using your own Modal app, paths, DNS, and operator CIDR.
docker compose --env-file .env --env-file modal.env \
  -f docker-compose.yml -f docker-compose.https.yml \
  -f "$MODAL_PACKAGE/compose/docker-compose.modal.yml" \
  -f "$MODAL_PACKAGE/compose/docker-compose.modal-edge.yml" config --quiet
docker compose --env-file .env --env-file modal.env \
  -f docker-compose.yml -f docker-compose.https.yml \
  -f "$MODAL_PACKAGE/compose/docker-compose.modal.yml" \
  -f "$MODAL_PACKAGE/compose/docker-compose.modal-edge.yml" up -d --wait
```

The catalog lists `modal-agent-server`. The fixture reserves a single
sandbox so the browser always accesses the correct HTTPS origin. Start a
synthetic conversation and verify an event in Enterprise. Run the
[preview fixture](../validation/preview_probe.py) on loopback port **8012**.
The guest's authenticated port 8011 wrapper serves its three routes.

Click Pause and confirm Enterprise reports PAUSED. Try a preview read and
verify it leaves the VM paused. Reopen the original conversation, measure
when the original message appears and when the preview check succeeds, and
verify both the boot marker and in-memory count survived. Compare the Modal
VM ID before and after. See [pilot timings](../README.md#enterprise-canvas-pilot).

Delete the owned sandbox via Sandbox V1, revoke temporary test credentials,
and stop the fixture. The synthetic memory snapshots follow Modal's
retention policy. The Compose overlay migration is additive. Consult the
Enterprise database migration runbook before switching the same database
back to an unmodified image.
