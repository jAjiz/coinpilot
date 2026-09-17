"""The facade over `core/db/`.

A call site imports this one module and writes `db.get_settings(session, user_id)`, so a
query that moves from one domain module to another does not touch any caller.

The direction is one way. The domain modules never import this file, and a unit test
holds them to it — a cycle here would make the import order load-bearing.
"""

from __future__ import annotations

from core.db.orders import (
    get_by_cl_ord_id,
    has_unresolved,
    list_orders,
    mark_failed,
    mark_filled,
    pending_orders,
    record_attempt,
)
from core.db.proposals import (
    get_live_proposal,
    get_proposal,
    save_proposal,
    set_status,
    withdraw,
)
from core.db.session import configure, get_engine, session_scope
from core.db.settings import (
    DueUser,
    create_settings,
    delete_asset,
    due_users,
    get_settings,
    list_assets,
    targets_for,
    update_settings,
    upsert_asset,
)
from core.db.telemetry import (
    delete_evaluations_before,
    finish_evaluation,
    latest_snapshot,
    list_evaluations,
    record_snapshot,
    snapshots_since,
    start_evaluation,
)
from core.db.users import (
    create_user,
    delete_credentials,
    get_credentials,
    get_user,
    get_user_by_identity,
    save_credentials,
    set_user_status,
)

__all__ = [
    "DueUser",
    "configure",
    "create_settings",
    "create_user",
    "delete_asset",
    "delete_credentials",
    "delete_evaluations_before",
    "due_users",
    "finish_evaluation",
    "get_by_cl_ord_id",
    "get_credentials",
    "get_engine",
    "get_live_proposal",
    "get_proposal",
    "get_settings",
    "get_user",
    "get_user_by_identity",
    "has_unresolved",
    "latest_snapshot",
    "list_assets",
    "list_evaluations",
    "list_orders",
    "mark_failed",
    "mark_filled",
    "pending_orders",
    "record_attempt",
    "record_snapshot",
    "save_credentials",
    "save_proposal",
    "session_scope",
    "set_status",
    "set_user_status",
    "snapshots_since",
    "start_evaluation",
    "targets_for",
    "update_settings",
    "upsert_asset",
    "withdraw",
]
