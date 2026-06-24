#!/usr/bin/env python3
"""Migrate Open WebUI ChromaDB memories to Honcho conclusions.

Run this inside the Open WebUI environment (or any Python environment with
chromadb and honcho-ai installed).  It reads every user's ChromaDB memory
collection and writes each fact as a conclusion from a synthetic "openwebui"
peer about that user.  Honcho's dreaming agent then processes these
conclusions into richer user representations over time.

Usage:
    python scripts/migrate.py \\
        --chromadb-data-dir /path/to/data/vector_db \\
        --honcho-api-key sk-... \\
        --identity-salt <same-salt-as-openwebui-env> \\
        [--honcho-base-url https://api.honcho.dev] \\
        [--honcho-workspace-id openwebui] \\
        [--dry-run]
"""

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional import — chromadb is a dependency of Open WebUI, not of this
# plugin, so it won't be in the plugin's venv.  Import inline so the argparse
# help still works even if it's missing.
# ---------------------------------------------------------------------------
try:
    import chromadb
except ImportError:
    print(
        "chromadb is not installed. Install it with:\n"
        "  pip install chromadb\n\n"
        "Or run this script inside the Open WebUI Python environment."
    )
    sys.exit(1)

from honcho import Honcho

# The derive_id helper is shared with the plugin so the peer IDs match.
# Import from the installed package when available, otherwise from the
# local source tree.
try:
    from openwebui_honcho.core import derive_id
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from openwebui_honcho.core import derive_id  # type: ignore[no-redef]


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate ChromaDB memories to Honcho conclusions")
    parser.add_argument(
        "--chromadb-data-dir",
        required=True,
        help="Path to the ChromaDB data directory (e.g. /app/backend/data/vector_db)",
    )
    parser.add_argument(
        "--honcho-api-key",
        required=True,
        help="Honcho API key",
    )
    parser.add_argument(
        "--honcho-base-url",
        default="https://api.honcho.dev",
        help="Honcho server URL (default: https://api.honcho.dev)",
    )
    parser.add_argument(
        "--honcho-workspace-id",
        default="openwebui",
        help="Honcho workspace ID (default: openwebui)",
    )
    parser.add_argument(
        "--identity-salt",
        required=True,
        help="Same OPENWEBUI_HONCHO_IDENTITY_SALT value set in the Open WebUI environment",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read ChromaDB and print what would be migrated without writing to Honcho",
    )
    args = parser.parse_args()

    data_dir = Path(args.chromadb_data_dir)
    if not data_dir.is_dir():
        print(f"Error: ChromaDB data directory not found: {data_dir}")
        sys.exit(1)

    # ---- Connect to ChromaDB ------------------------------------------------
    print(f"Opening ChromaDB at {data_dir} ...")
    try:
        client = chromadb.PersistentClient(path=str(data_dir))
    except Exception as exc:
        print(f"Error: Could not open ChromaDB: {exc}")
        print("Make sure the path is correct and not locked by a running Open WebUI.")
        sys.exit(1)

    collections = client.list_collections()
    # Normalise: newer chromadb returns Collection objects, older returns names.
    collection_names: list[str] = []
    for c in collections:
        if isinstance(c, str):
            collection_names.append(c)
        else:
            collection_names.append(c.name)

    user_collections = [n for n in collection_names if n.startswith("user-memory-")]
    if not user_collections:
        print("No user-memory-* collections found. Nothing to migrate.")
        sys.exit(0)

    print(f"Found {len(user_collections)} user memory collection(s).")

    # ---- Connect to Honcho --------------------------------------------------
    if not args.dry_run:
        honcho = Honcho(
            api_key=args.honcho_api_key,
            base_url=args.honcho_base_url,
            workspace_id=args.honcho_workspace_id,
        )
    else:
        honcho = None  # type: ignore[assignment]

    # The synthetic peer represents "Open WebUI" as an observer of every user.
    ow_peer_id = derive_id("ow", "openwebui", args.identity_salt)
    if not args.dry_run:
        ow_peer = honcho.peer(ow_peer_id)  # type: ignore[union-attr]
        print(f"Open WebUI synthetic peer: {ow_peer_id}")
    else:
        print(f"[DRY RUN] Would create/get synthetic peer: {ow_peer_id}")

    total_facts = 0
    total_users = 0
    batch_size = 100  # Honcho API limit per request

    for collection_name in sorted(user_collections):
        user_id = collection_name[len("user-memory-") :]
        if not user_id:
            continue

        collection = client.get_collection(collection_name)
        try:
            results = collection.get()
        except Exception as exc:
            print(f"✗ {user_id}: failed to read collection — {exc}")
            continue

        documents = results.get("documents") if isinstance(results, dict) else None
        if not documents:
            print(f"  {user_id}: 0 facts — skipping")
            continue

        facts: list[str] = [d for d in documents if isinstance(d, str) and d.strip()]
        if not facts:
            print(f"  {user_id}: 0 non-empty facts — skipping")
            continue

        user_peer_id = derive_id("usr", user_id, args.identity_salt)

        if not args.dry_run:
            user_peer = honcho.peer(user_peer_id)  # type: ignore[union-attr]
            scope = ow_peer.conclusions_of(user_peer)  # type: ignore[union-attr]

            batches = 0
            for i in range(0, len(facts), batch_size):
                batch = facts[i : i + batch_size]
                scope.create([{"content": fact} for fact in batch])
                batches += 1

            print(f"✓ {user_id}: {len(facts)} facts → {batches} batch(es)")
        else:
            batches = (len(facts) + batch_size - 1) // batch_size
            print(
                f"[DRY RUN] {user_id}: {len(facts)} facts → {batches} batch(es) "
                f"→ conclusions of {user_peer_id}"
            )

        total_facts += len(facts)
        total_users += 1

    action = "[DRY RUN] Would migrate" if args.dry_run else "Migrated"
    print(f"\n{action} {total_facts} facts for {total_users} users.")


if __name__ == "__main__":
    main()
