"""The live proposal.

One row per user, and the status says what is in the slot. A withdrawn proposal keeps its
row so a reader can tell *there was one and it went away* from *there was never one*.

The `plan` column is JSON, and JSON has no decimal type. Every amount must already be a
string when it arrives here. A float would lose money silently.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import Proposal
from core.db.types import ProposalStatus, ProposalTrigger


def get_proposal(session: Session, user_id: uuid.UUID) -> Proposal | None:
    """Whatever is in this user's slot, whatever its status."""
    stmt = select(Proposal).where(Proposal.user_id == user_id)
    return session.execute(stmt).scalar_one_or_none()


def get_live_proposal(session: Session, user_id: uuid.UUID) -> Proposal | None:
    """The proposal only while it is live. A withdrawn or executed one is not offered."""
    proposal = get_proposal(session, user_id)
    if proposal is None or proposal.status != ProposalStatus.LIVE:
        return None
    return proposal


def save_proposal(
    session: Session,
    user_id: uuid.UUID,
    plan: dict[str, object],
    trigger: ProposalTrigger,
    version: int,
) -> Proposal:
    """Write this user's proposal, reusing the slot if one is already there.

    The version arrives decided. What counts as a material change is the caller's
    judgement, and this layer only stores the number it arrived at.
    """
    proposal = get_proposal(session, user_id)
    if proposal is None:
        proposal = Proposal(user_id=user_id)
        session.add(proposal)
    proposal.plan = plan
    proposal.trigger = trigger
    proposal.version = version
    proposal.status = ProposalStatus.LIVE
    session.flush()
    return proposal


def set_status(session: Session, user_id: uuid.UUID, status: ProposalStatus) -> Proposal | None:
    proposal = get_proposal(session, user_id)
    if proposal is None:
        return None
    proposal.status = status
    session.flush()
    return proposal


def withdraw(session: Session, user_id: uuid.UUID) -> bool:
    """True when there was a proposal to withdraw, false when there was none."""
    return set_status(session, user_id, ProposalStatus.WITHDRAWN) is not None
