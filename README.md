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
