# Modal for OpenHands Canvas

This package contains the Enterprise Compose pilot and documents the earlier
standalone Agent Server controller prototype.

## Enterprise Canvas pilot

The [Enterprise overlay](enterprise-pilot/) uses the same managed sandbox
service, sandbox spec catalog, event callbacks, and Canvas Pause and resume
APIs as the E2B and DigitalOcean pilots. The Enterprise sandbox and conversation
IDs stay stable. The adapter stores the Modal snapshot and rebinds the original
authenticated Agent Server and preview routes to the replacement VM on resume.

Two trials reopened the same original conversation through Chromium running on
the isolated AWS Compose host. Both used Enterprise 1.88.0, Canvas 1.35.0 with
the shared Pause capability, Agent Server 1.62.0, and a 2-vCPU, 2-GiB Modal VM.
The agent stayed idle and the fixture made no model calls.

| Measured step | Trial 1 | Trial 2 |
|---|---:|---:|
| Click Pause to settled PAUSED | 3.763 s | 2.522 s |
| Reopen original conversation to history visible | 0.116 s | 0.105 s |
| Reopen original conversation to resume acknowledged | 2.107 s | 2.093 s |
| Reopen original conversation to preview authorization | 4.821 s | 4.776 s |
| Reopen original conversation to successful interactive preview check | 6.119 s | 6.069 s |

Enterprise returned the stored history while the VM was paused. Canvas then
rendered the same message and loaded the embedded preview under the original
conversation. The preview kept its original boot marker, process ID,
workspace marker and counter, and a new click advanced the counter.
Provider checks confirmed a replacement Modal VM and tunnel. Anonymous
preview requests were rejected by both the Enterprise
gateway and the raw Modal tunnel. An authenticated request while paused
returned 409 and left the VM paused.

The test uses Modal's alpha memory snapshots and an isolated HTTPS origin for
one test sandbox. The guest preview shim serves the synthetic fixture's three
HTTP endpoints. General-purpose developer previews, snapshot expiry recovery,
and automated pause are outside this validation. The release overlay assumes
the unmodified Enterprise 1.88.0 base image and its migration head.

After the test, the Modal VM was terminated, the fixture API key was revoked,
the copied Modal credential was removed from AWS, and the isolated host was
stopped. Modal retains the synthetic memory snapshots until the provider's
seven-day expiry.

## Standalone controller prototype

| Seam | Modal prototype mapping |
|---|---|
| Environment | The controller creates a distinct VM and Agent Server per conversation. Pin the sandbox image and VM size used for a test. |
| Ownership and lifecycle | The controller persists conversation bindings in a private catalog. Hibernation records a filesystem snapshot and terminates the runtime. Reprovision creates a replacement runtime. |
| Guest identity and events | The controller keeps provider credentials, verifies conversation access, and caches accessible history. A native Enterprise adapter needs standard ownership and callback checks. |
| Runtime traffic | The controller proxies HTTP and WebSockets. Revalidate preview setup and browser access after replacing the runtime. |
| Persistence | Filesystem snapshots restore files. The preview needs a new process. Modal memory snapshots are a separate alpha capability. |
| Cleanup | Delete the known test sandbox and account for retained filesystem snapshots. |

Qualify providers using the shared [Canvas acceptance test](../openhands-provider-contract/CANVAS.md). The standalone controller implements workspace restore. See [Modal snapshot behavior](https://modal.com/docs/guide/sandbox-snapshots).


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
This run exercised the standalone controller.

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

A follow-up used OpenHands Agent Server 1.62.0 with a preview started through
its terminal API. The 2-vCPU, 2-GiB VM took 3.806 s to snapshot and 0.915 s to
restore through a successful Agent Server and HTTPS preview check. The preview
kept its in-memory counter and accepted a new request. Both sandboxes were
terminated. This trial exercised the guest launch path.
