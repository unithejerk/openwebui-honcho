#!/usr/bin/env python3
"""Install the Honcho Memory plugin into an Open WebUI instance via its API."""

import argparse
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

PLUGINS = [
    {
        "file": "honcho_memory.py",
        "type": "function",
        "id": "honcho_memory",
        "endpoint": "/api/v1/functions",
    },
    {
        "file": "honcho_memory_actions.py",
        "type": "function",
        "id": None,  # uses the file stem as the function id
        "endpoint": "/api/v1/functions",
    },
    {
        "file": "honcho_memory_tools.py",
        "type": "tool",
        "id": "honcho_memory_tools",
        "endpoint": "/api/v1/tools",
    },
]

# Prevent any single API call from hanging the installer indefinitely.
_REQUEST_TIMEOUT = 30


def _function_url(base: str, func_id: str) -> str:
    return f"{base}/api/v1/functions/id/{func_id}"


def _tool_url(base: str, tool_id: str) -> str:
    return f"{base}/api/v1/tools/id/{tool_id}"


def _create(session: requests.Session, base: str, endpoint: str, body: dict, headers: dict) -> dict:
    r = session.post(
        f"{base}{endpoint}/create", json=body, headers=headers, timeout=_REQUEST_TIMEOUT
    )
    r.raise_for_status()
    return r.json()


def _update(
    session: requests.Session,
    base: str,
    resource_type: str,
    obj_id: str,
    content: str,
    headers: dict,
) -> dict:
    ep = _function_url if resource_type == "function" else _tool_url
    r = session.post(
        f"{ep(base, obj_id)}/update",
        json={"id": obj_id, "content": content},
        headers=headers,
        timeout=_REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def _exists(
    session: requests.Session, base: str, resource_type: str, obj_id: str, headers: dict
) -> bool:
    ep = _function_url if resource_type == "function" else _tool_url
    r = session.get(f"{ep(base, obj_id)}", headers=headers, timeout=_REQUEST_TIMEOUT)
    if r.status_code == 404:
        return False
    r.raise_for_status()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Honcho Memory into Open WebUI")
    parser.add_argument("--base-url", default="http://localhost:3000", help="Open WebUI base URL")
    parser.add_argument(
        "--api-key",
        help="Admin API key (required unless --dry-run is used)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without making any API calls",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.api_key:
        parser.error("--api-key is required unless --dry-run is used")

    base = args.base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {args.api_key}", "Content-Type": "application/json"}

    failures = 0
    # Reuse TCP connections across the three plugin uploads.
    with requests.Session() as session:
        for plugin in PLUGINS:
            path = DIST / plugin["file"]
            if not path.exists():
                print(f"✗ Missing {path} — run scripts/generate_plugins.py first")
                sys.exit(1)

            obj_id = plugin["id"] or path.stem
            endpoint = plugin["endpoint"]
            resource_type = plugin["type"]

            if args.dry_run:
                print(
                    f"[DRY RUN] Would CREATE or UPDATE {resource_type} {obj_id} from {plugin['file']}"
                )
                continue

            try:
                content = path.read_text()
                if _exists(session, base, resource_type, obj_id, headers):
                    _update(session, base, resource_type, obj_id, content, headers)
                    print(f"✓ Updated {resource_type} {obj_id}")
                else:
                    body = {"id": obj_id, "content": content}
                    if resource_type == "tool":
                        body["access_grants"] = []
                    _create(session, base, endpoint, body, headers)
                    print(f"✓ Created {resource_type} {obj_id}")
            except requests.RequestException as exc:
                failures += 1
                print(f"✗ Failed to install {resource_type} {obj_id} from {plugin['file']}: {exc}")

    if failures:
        print(f"\n{failures} plugin(s) could not be installed.")
        sys.exit(1)

    print("\nDone. The Honcho Filter should now appear in chat settings and Tools in Workspace.")


if __name__ == "__main__":
    main()
