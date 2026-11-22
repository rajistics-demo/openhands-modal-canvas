# Provider-aware Canvas 1.35.0 pilot

The patch in this directory is the Canvas candidate used for the earlier
isolated provider tests. Apply it to the pinned upstream checkout. The
patch changes Canvas, so the selected Enterprise adapter also needs to
advertise `sandbox_supports_runtime_pause` on conversations. Check that
field before expecting the **Pause** menu item. Stock providers that
do not advertise it can still be qualified using the Sandbox V1 API.

## Build for an isolated origin

Use Node 24 and npm with the lockfile in the upstream checkout.

```sh
export PROVIDER_PACKAGE=/absolute/path/to/provider-example
git clone --filter=blob:none https://github.com/OpenHands/OpenHands.git canvas-pilot
cd canvas-pilot
git checkout --detach 934612b3b6cee05d3a4400b98b48a9c69215401d
git apply --check "$PROVIDER_PACKAGE/canvas/canvas-1.35.0-provider-pause.patch"
git apply "$PROVIDER_PACKAGE/canvas/canvas-1.35.0-provider-pause.patch"
npm ci
VITE_BASE_PATH=/canvas VITE_CANVAS_RECOVERY_PILOT_ORIGIN=https://openhands.example.com npm run build
```

Use your actual isolated HTTPS origin in the build. Set
`AGENT_CANVAS_LOCK_TO_CLOUD` to the same origin on the stock Canvas service.
Set `CANVAS_PILOT_BUILD` to the absolute path of the built `build/` directory.
Append [the Canvas Compose override](docker-compose.canvas-pause.yml) to
the provider's Compose file list before `config --quiet` and `up -d --wait`.
It mounts the build read-only at `/opt/agent-canvas/frontend`.

## Validate

Run the Pause and reopen test below using one disposable
conversation and [the preview fixture](../validation/preview_probe.py). Record the
provider spec, image version and backend patch. The browser accepts
credentialed preview origins at `<sandbox-id>.preview.<app-host>`.
The legacy AWS and E2B preview paths depend on the pilot origin and a
conversation tagged `canvasrecoverypilotpreview=true`. Configure the
AWS demo runtime host as `runtime-repo.<app-host>` for that path and
use synthetic preview content.

The existing checkpoint recovery hooks are gated on the backend's
`recovery_available` field and the configured pilot origin. Sandbox Pause
and resume alone do not qualify post-expiry workspace recovery.

The patch applied to a clean copy of the pinned source and passed 66 focused
tests covering the Pause action, conversation routing, and preview. Those
checks used the upstream lockfile dependencies already installed for 1.35.0.
The same pinned build passed the shared browser test on isolated Modal
Enterprise Compose. The provider setup guides and status records describe
coverage for each package.

## Time Pause and reopen in Chromium

Create one owned synthetic conversation, deliver a distinct history marker
to Enterprise, and start the shared preview fixture. Use the exact
workspace, callback, and preview configuration from the provider's guide.
Run on a host that can reach both allowed browser origins. An operator
should capture the browser storage state for the disposable account only.
For example, use Playwright's `codegen --save-storage` option and close the
browser after signing in.

Keep browser storage state and fixture identifiers in an ignored `.private/`
directory. Use these fields in `.private/canvas-fixture.json`:

```json
{
  "isolated": true,
  "origin": "https://openhands.example.com",
  "storageState": ".private/canvas-storage.json",
  "principalId": "a0000000-0000-0000-0000-000000000001",
  "orgId": "a0000000-0000-0000-0000-000000000002",
  "conversationId": "a0000000-0000-0000-0000-000000000003",
  "sandboxId": "fixture-sandbox",
  "title": "Synthetic provider fixture",
  "historyMarker": "OpenHands provider history marker",
  "preview": "https://fixture-sandbox.preview.openhands.example.com/",
  "authenticatedPreview": true,
  "checkPausedPreview": true
}
```

For an older AWS or E2B pilot preview without a browser auth challenge, set
`authenticatedPreview` to false. Enable `checkPausedPreview` only when
the provider's documented preview route returns HTTP 409 while paused.

```sh
npm install --prefix canvas --no-save playwright@1.61.1
npx --prefix canvas playwright install chromium
node canvas/smoke.mjs .private/canvas-fixture.json
```

The runner checks account and sandbox ownership, clicks Pause, reads
persisted history while the VM remains paused, and reopens the original
conversation. It emits only milestone timings and the pass result. Check
the provider's actual VM ID before and after to distinguish a native
resume from memory restore into a replacement. Retire the fixture with
the provider's documented cleanup. A failure may leave the sandbox paused,
so inspect its state before trying again.
