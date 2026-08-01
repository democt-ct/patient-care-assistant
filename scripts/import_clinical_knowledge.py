"""Import reviewed or pending clinical knowledge from a governed JSON manifest.

Usage:
  python scripts/import_clinical_knowledge.py data/clinical_knowledge.json --dry-run
  python scripts/import_clinical_knowledge.py data/clinical_knowledge.json --apply
  python scripts/import_clinical_knowledge.py data/clinical_knowledge.json --apply --publish
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.services.clinical_knowledge_governance import (
    ClinicalKnowledgeValidationError,
    validate_clinical_knowledge_payload,
)
from app.services.memory_extraction_service import upsert_knowledge_chunk


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    records = payload.get("chunks") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("Manifest must be a JSON array or an object with a chunks array")
    if not all(isinstance(item, dict) for item in records):
        raise ValueError("Every manifest item must be a JSON object")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Import governed clinical knowledge")
    parser.add_argument("manifest", type=Path, help="UTF-8 JSON manifest")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Validate only; do not write to the database")
    mode.add_argument("--apply", action="store_true", help="Write validated records to the database")
    parser.add_argument("--publish", action="store_true", help="Allow manifest records marked approved")
    parser.add_argument("--sync-vector", action="store_true", help="Synchronize vectors immediately (may load embedding models)")
    args = parser.parse_args()

    try:
        records = _load_manifest(args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Manifest error: {exc}", file=sys.stderr)
        return 2

    valid: list[dict[str, Any]] = []
    failures: list[str] = []
    for index, record in enumerate(records, start=1):
        try:
            valid.append(validate_clinical_knowledge_payload(record, allow_publish=args.publish))
        except ClinicalKnowledgeValidationError as exc:
            failures.append(f"record {index}: {exc}")

    if failures:
        print("Import rejected:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 2
    if args.dry_run:
        print(f"Validated {len(valid)} clinical knowledge records; no database changes made.")
        return 0

    db = SessionLocal()
    try:
        for record in valid:
            upsert_knowledge_chunk(db, payload=record, sync_vector=args.sync_vector)
    finally:
        db.close()
    print(f"Imported {len(valid)} clinical knowledge records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
