# Modal for OpenHands Canvas

This package documents the existing remote Agent Server controller prototype and the proposed Enterprise integration. The implementation and tests remain in the Modal prototype checkout.

| Seam | Modal prototype mapping |
|---|---|
| Environment | The controller creates a distinct VM and Agent Server per conversation. Pin the sandbox image and VM size used for a test. |
| Ownership and lifecycle | The controller persists conversation bindings in a private catalog. Hibernation records a filesystem snapshot and terminates the runtime. Reprovision creates a replacement runtime. |
| Guest identity and events | The controller keeps provider credentials, verifies conversation access, and caches accessible history. A native Enterprise adapter needs standard ownership and callback checks. |
| Runtime traffic | The controller proxies HTTP and WebSockets. Revalidate preview setup and browser access after replacing the runtime. |
| Persistence | Filesystem snapshots restore files. The preview needs a new process. Modal memory snapshots are a separate alpha capability. |
| Cleanup | Delete the known test sandbox and account for retained filesystem snapshots. |

Qualify the existing remote backend using the same observable workflow in the [Canvas acceptance test](../openhands-provider-contract/CANVAS.md). Use a capability label of workspace restore for the current prototype. A native Enterprise Pause test requires an Enterprise adapter. See [Modal snapshot behavior](https://modal.com/docs/guide/sandbox-snapshots).


## Controller restore check

Use the installed OpenHands Agent Server checkout that includes the Modal
conversation controller and a configured Modal profile for your existing
prototype app. Supply the app name explicitly. The probe creates one
disposable VM, adds a synthetic history message, hibernates, then reads history
and resumes the workspace on a replacement VM. It starts a new preview
process in the guest and removes the runtime and filesystem snapshot.

```bash
python controller_restore_probe.py \
  --app "$MODAL_TEST_APP" \
  --work .private/modal-controller-probe \
  --preview-probe ../openhands-provider-contract/preview_probe.py
```

The November 21 pilot recovered the file and the original conversation.
History was available through the controller in 5 ms while hibernated.
Reopen through a working preview inside the restored guest took 7.75 s and 10.61 s in two runs.
A native Enterprise or Canvas browser result remains unverified.

## VM memory restore check

Run with Modal SDK 1.6.0 and the shared synthetic preview fixture. The probe
uses an existing Modal app and one 1-vCPU, 512-MiB sandbox at a time. The
preview is the sandbox entrypoint. It exposes a random boot marker and an
in-memory counter through a temporary HTTPS tunnel.

```bash
python memory_restore_probe.py \
  --app "$MODAL_TEST_APP" \
  --preview-probe ../openhands-provider-contract/preview_probe.py
```

| Timed operation | Trial 1 | Trial 2 |
|---|---:|---:|
| Fresh VM request to HTTPS preview response | 0.872 s | 0.983 s |
| Memory snapshot request to completion | 2.512 s | 2.323 s |
| Snapshot restore request to HTTPS preview response | 0.470 s | 0.475 s |

In both trials the source stopped, and the replacement had a different sandbox
ID and tunnel. The HTTPS preview returned the same boot marker and counter
value. A new request advanced the counter. The probe confirmed sandbox
termination. These timings cover a synthetic provider-level preview.

The [Modal memory snapshot API](https://modal.com/docs/guide/sandbox-snapshots#memory-snapshots)
is alpha. Memory snapshots retain the synthetic state for up to seven days.
Modal closes existing TCP connections on snapshot and excludes previews
launched through sandbox exec. The Enterprise adapter needs to resolve the
new tunnel behind the original authenticated conversation URL and verify the
actual Canvas preview launch path. The filesystem checkpoint remains the
recovery path for workspaces after a memory snapshot expires.
