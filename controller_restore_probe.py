"""Live restore probe through the existing OpenHands Modal controller."""

import argparse
import asyncio
import base64
import json
import os
import secrets
import shlex
import time
from pathlib import Path
from uuid import uuid4

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--app", required=True, help="Existing Modal prototype application")
parser.add_argument(
    "--work", required=True, type=Path, help="New directory for private test state"
)
parser.add_argument(
    "--preview-probe", required=True, type=Path, help="Shared preview_probe.py path"
)
args = parser.parse_args()
if ".private" not in args.work.resolve().parts:
    parser.error("--work must be a new directory under an ignored .private path")
if not args.preview_probe.is_file():
    parser.error("--preview-probe must be an existing file")
state = args.work.resolve()
state.mkdir(mode=0o700)
os.environ["OH_PERSISTENCE_DIR"] = str(state / "persistence")
os.environ["OH_CONVERSATIONS_PATH"] = str(state / "conversations")
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
for setting in (
    "LMNR_PROJECT_API_KEY",
    "OTEL_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
):
    os.environ.pop(setting, None)

import httpx
import modal
import modal.experimental
from pydantic import SecretStr
from openhands.agent_server.api import create_app
from openhands.agent_server.config import Config
from openhands.agent_server.modal_runtime.registry import ModalConversationRegistry


async def main():
    app_name = args.app
    # Reuse the existing authenticated prototype application. No app creation
    # or default changes are required to launch the isolated conversation VM.
    await modal.App.lookup.aio(app_name, create_if_missing=False)
    key = secrets.token_urlsafe(32)
    config = Config(
        conversation_runtime="modal",
        conversations_path=state / "conversations",
        workspace_path=state / "workspace",
        secret_key=SecretStr(secrets.token_urlsafe(32)),
        session_api_keys=[key],
        modal_app_name=app_name,
        modal_timeout_seconds=900,
        modal_snapshot_ttl_seconds=600,
        modal_max_sandboxes=2,
        conversation_container_startup_timeout=120,
    )
    app = create_app(config)
    registry = app.state.conversation_registry
    assert isinstance(registry, ModalConversationRegistry)
    await registry.start()
    cid = uuid4()
    route = f"/api/conversations/{cid}"
    snapshot_id = None
    receipt = state / "receipt.json"
    receipt.write_text(json.dumps({"conversation": str(cid)}))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Session-API-Key": key},
        timeout=160,
    ) as client:

        async def execute(command):
            response = await client.post(
                route + "/bash/execute_bash_command",
                json={"command": command, "cwd": "/workspace", "timeout": 45},
            )
            response.raise_for_status()
            result = response.json()
            assert result["exit_code"] == 0
            return result.get("stdout") or result.get("output") or ""

        try:
            created = await client.post(
                "/api/conversations",
                json={
                    "conversation_id": str(cid),
                    "agent": {
                        "kind": "Agent",
                        "tools": [],
                        "llm": {
                            "model": "openai/gpt-4.1-mini",
                            "api_key": "synthetic-unused-key",
                            "usage_id": "modal-provider-replay",
                        },
                    },
                    "workspace": {
                        "kind": "LocalWorkspace",
                        "working_dir": "/workspace",
                    },
                    "autotitle": False,
                },
            )
            created.raise_for_status()
            before_target = await registry.ensure(cid)
            marker = "Synthetic Modal history marker"
            message = await client.post(
                route + "/events",
                json={
                    "role": "user",
                    "content": [{"type": "text", "text": marker}],
                    "run": False,
                },
            )
            message.raise_for_status()
            source = base64.b64encode(args.preview_probe.read_bytes()).decode()
            await execute(
                "mkdir -p /workspace/fixture; printf modal-workspace > /workspace/fixture/workspace-marker.txt; "
                + "printf %s "
                + shlex.quote(source)
                + " | base64 -d > /workspace/fixture/preview.py"
            )
            start_preview = "cd /workspace/fixture && (setsid nohup python3 preview.py --port 8011 > /tmp/modal-preview.log 2>&1 < /dev/null &)"
            check = "python3 -c " + shlex.quote(
                "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8011/state',timeout=4).read().decode())"
            )
            await execute(start_preview)
            await asyncio.sleep(0.5)
            before = json.loads((await execute(check)).strip())
            assert before["count"] == 0
            stopped = await client.post(route + "/runtime/hibernate")
            stopped.raise_for_status()
            record = registry.store.load(cid)
            assert record.phase == "hibernated" and record.snapshot_id
            snapshot_id = record.snapshot_id
            receipt.write_text(
                json.dumps(
                    {
                        "conversation": str(cid),
                        "snapshot_id": snapshot_id,
                        "old_sandbox_id": before_target.sandbox_id,
                    }
                )
            )
            started = time.monotonic()
            history = await client.get(route + "/events/search")
            history.raise_for_status()
            assert marker in history.text
            history_time = time.monotonic() - started
            assert registry.store.load(cid).phase == "hibernated"
            await execute(
                'test "$(cat /workspace/fixture/workspace-marker.txt)" = modal-workspace'
            )
            restored_target = await registry.ensure(cid)
            assert restored_target.sandbox_id != before_target.sandbox_id
            await execute(start_preview)
            await asyncio.sleep(0.5)
            after = json.loads((await execute(check)).strip())
            assert after["count"] == 0 and after["boot"] != before["boot"]
            result = {
                "sameConversation": True,
                "replacementVm": True,
                "workspaceRestored": True,
                "historyReadStayedHibernated": True,
                "previewProcessRestarted": True,
                "openHistorySeconds": round(history_time, 3),
                "controllerReopenThroughGuestPreviewSeconds": round(
                    time.monotonic() - started, 2
                ),
            }
            (state / "summary.json").write_text(json.dumps(result))
            print(json.dumps(result), flush=True)
        finally:
            try:
                if registry.store.path(cid).exists():
                    await registry.delete(cid)
                    print("Removed the task-owned Modal runtime.", flush=True)
                if snapshot_id:
                    await modal.experimental.image_delete.aio(snapshot_id)
                    print("Removed the task-owned Modal snapshot.", flush=True)
            finally:
                await registry.shutdown()


asyncio.run(main())
