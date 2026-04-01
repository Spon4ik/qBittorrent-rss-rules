from __future__ import annotations

from sqlalchemy import select

from app.db import get_session_factory, init_db
from app.models import Rule, RuleSearchSnapshot
from app.services.rule_fetch_ops import refresh_snapshot_release_cache


def main() -> int:
    init_db()
    session = get_session_factory()()
    try:
        rules = session.scalars(select(Rule)).all()
        snapshots = {
            item.rule_id: item for item in session.scalars(select(RuleSearchSnapshot)).all()
        }
        updated = 0
        for rule in rules:
            snapshot = snapshots.get(rule.id)
            if snapshot is None:
                continue
            if refresh_snapshot_release_cache(snapshot, rule=rule):
                updated += 1
        if updated:
            session.commit()
        print(f"Updated {updated} snapshot release caches out of {len(snapshots)} snapshots.")
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
