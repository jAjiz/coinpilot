import uuid

import pytest
from sqlalchemy.orm import Session

from core.db.proposals import (
    get_live_proposal,
    get_proposal,
    save_proposal,
    set_status,
    withdraw,
)
from core.db.types import ProposalStatus, ProposalTrigger

PLAN = {"legs": [{"asset": "BTC", "side": "sell", "amount_fiat": "100.00"}]}


def test_a_saved_proposal_is_live_at_the_version_the_caller_chose(db_session: Session, make_user):
    proposal = save_proposal(
        db_session, make_user().id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=3
    )

    assert proposal.status == ProposalStatus.LIVE
    assert proposal.version == 3
    assert proposal.trigger == ProposalTrigger.SCHEDULED


def test_saving_again_replaces_the_one_slot_rather_than_adding_a_second(db_session: Session, make_user):
    user = make_user()
    first = save_proposal(db_session, user.id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=1)

    second = save_proposal(db_session, user.id, plan=PLAN, trigger=ProposalTrigger.MANUAL, version=2)

    assert second.id == first.id
    assert second.version == 2
    assert second.trigger == ProposalTrigger.MANUAL


def test_the_plan_comes_back_exactly_as_it_went_in(db_session: Session, make_user):
    """Amounts are strings. JSON has no decimal type and a float would lose money."""
    saved = save_proposal(db_session, make_user().id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=1)
    db_session.expire(saved)

    assert saved.plan == PLAN
    assert saved.plan["legs"][0]["amount_fiat"] == "100.00"


def test_a_withdrawn_proposal_is_no_longer_live_but_the_row_remains(db_session: Session, make_user):
    user = make_user()
    save_proposal(db_session, user.id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=1)

    withdraw(db_session, user.id)

    assert get_live_proposal(db_session, user.id) is None
    assert get_proposal(db_session, user.id).status == ProposalStatus.WITHDRAWN


def test_withdrawing_says_whether_there_was_a_proposal(db_session: Session, make_user):
    user = make_user()

    assert withdraw(db_session, user.id) is False

    save_proposal(db_session, user.id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=1)
    assert withdraw(db_session, user.id) is True


def test_a_new_proposal_revives_a_withdrawn_slot(db_session: Session, make_user):
    """Drift came back. The slot is reused rather than a second row being created."""
    user = make_user()
    save_proposal(db_session, user.id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=1)
    withdraw(db_session, user.id)

    revived = save_proposal(db_session, user.id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=2)

    assert revived.status == ProposalStatus.LIVE


def test_the_status_moves_through_execution(db_session: Session, make_user):
    user = make_user()
    save_proposal(db_session, user.id, plan=PLAN, trigger=ProposalTrigger.MANUAL, version=1)

    set_status(db_session, user.id, ProposalStatus.EXECUTING)
    assert get_proposal(db_session, user.id).status == ProposalStatus.EXECUTING

    set_status(db_session, user.id, ProposalStatus.EXECUTED)
    assert get_proposal(db_session, user.id).status == ProposalStatus.EXECUTED


def test_a_user_with_no_proposal_has_none(db_session: Session, make_user):
    user = make_user()

    assert get_proposal(db_session, user.id) is None
    assert get_live_proposal(db_session, user.id) is None
    assert set_status(db_session, user.id, ProposalStatus.EXECUTED) is None


def test_an_unknown_user_has_no_proposal(db_session: Session):
    assert get_proposal(db_session, uuid.uuid4()) is None


@pytest.mark.parametrize("status", [member.value for member in ProposalStatus])
def test_every_proposal_status_the_code_knows_is_accepted(db_session: Session, make_user, status):
    user = make_user()
    proposal = save_proposal(db_session, user.id, plan=PLAN, trigger=ProposalTrigger.SCHEDULED, version=1)

    proposal.status = status
    db_session.flush()
