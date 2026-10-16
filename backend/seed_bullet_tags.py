#!/usr/bin/env python
"""Create the starter Bullet Bank tags from data/bullet_tags_seed.json.

    .venv/bin/python seed_bullet_tags.py

Safe to re-run: a tag whose name already exists is skipped, never
overwritten, so edits made in the app are kept.
"""

import json
from pathlib import Path

from app.bullet_bank_service import BulletBankError, create_tag

SEED = Path(__file__).parent / "data" / "bullet_tags_seed.json"


def main() -> int:
    created = skipped = 0
    for tag in json.loads(SEED.read_text()):
        try:
            create_tag(tag["name"], tag["category"], tag["definition"])
            created += 1
        except BulletBankError:
            skipped += 1
    print(f"Created {created} tag(s), skipped {skipped} already present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
