"""Measure Modal VM snapshot and recovery with a synthetic HTTP preview."""

import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

import modal

PORT = 8011


def report(**fields):
    print(json.dumps(fields), flush=True)


def check(url, method="GET"):
    path = "/check" if method == "POST" else "/state"
    deadline = time.monotonic() + 35
    while True:
        try:
            with urlopen(Request(url + path, method=method), timeout=3) as response:
                return json.load(response)
        except OSError:
            if method == "POST" or time.monotonic() > deadline:
                raise
            time.sleep(0.25)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, help="Existing Modal prototype application")
    parser.add_argument("--preview-probe", required=True, type=Path)
    args = parser.parse_args()
    if not args.preview_probe.is_file():
        parser.error("--preview-probe must be an existing file")

    # The preview is the initial sandbox process. Processes started by exec
    # are outside Modal's memory snapshot guarantee.
    preview_source = args.preview_probe.read_text()
    sandboxes = []
    cleanup_failed = False
    step = "app lookup"
    try:
        app = modal.App.lookup(args.app, create_if_missing=False)
        step = "create"
        started = time.monotonic()
        original = modal.Sandbox.create(
            "python3", "-u", "-c", preview_source,
            "--port", str(PORT), "--listen", "0.0.0.0",
            app=app,
            runtime="vm",
            _experimental_enable_snapshot=True,
            timeout=240,
            encrypted_ports=[PORT],
            cpu=1,
            memory=512,
        )
        sandboxes.append(original)
        step = "fresh preview"
        original_tunnel = original.tunnels(timeout=45)[PORT].url
        check(original_tunnel)
        report(stage=step, seconds=round(time.monotonic() - started, 3))
        first = check(original_tunnel, "POST")
        assert first["count"] == 1
        step = "snapshot"
        started = time.monotonic()
        snapshot = original._experimental_snapshot()
        report(stage=step, seconds=round(time.monotonic() - started, 3))
        report(original_stopped=original.poll() is not None)
        step = "restore"
        started = time.monotonic()
        restored = modal.Sandbox._experimental_from_snapshot(snapshot)
        sandboxes.append(restored)
        assert original.object_id != restored.object_id
        report(stage="restore returned", seconds=round(time.monotonic() - started, 3))
        step = "restored preview"
        restored_tunnel = restored.tunnels(timeout=45)[PORT].url
        second = check(restored_tunnel)
        report(stage=step, seconds=round(time.monotonic() - started, 3))
        third = check(restored_tunnel, "POST")
        assert first == second
        assert third == dict(first, count=2)
        report(
            process_state_preserved=True,
            tunnel_changed=original_tunnel != restored_tunnel,
            new_sandbox=True,
        )
    except Exception as exc:
        # Raw diagnostics stay private. The caller only sees the stage and exception class.
        report(failed_stage=step, error=type(exc).__name__)
        return 1
    finally:
        for sandbox in reversed(sandboxes):
            try:
                if sandbox.poll() is None:
                    sandbox.terminate(wait=True)
                stopped = sandbox.poll() is not None
                report(cleanup_confirmed=stopped)
                cleanup_failed |= not stopped
            except Exception as exc:
                report(cleanup_error=type(exc).__name__)
                cleanup_failed = True
    return int(cleanup_failed)


if __name__ == "__main__":
    raise SystemExit(main())
