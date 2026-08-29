"""Tests for the human approval gate before PR creation."""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.routes.remediation import generate_draft_pr


@pytest.mark.asyncio
async def test_generate_pr_rejects_unapproved_fix():
    fix = MagicMock(status="generated", investigation_id="inv-1")
    investigation = MagicMock(id="inv-1", incident_id="inc-1")
    incident = MagicMock(id="inc-1", creator_id=None, scopes=[])
    db = MagicMock()
    # 1: fix, 2: investigation, 3: incident, 4: approval (None)
    db.query.return_value.filter.return_value.first.side_effect = [fix, investigation, incident, None]

    with pytest.raises(HTTPException) as error:
        await generate_draft_pr(
            MagicMock(investigation_id="inv-1", fix_id="fix", branch_name=None),
            MagicMock(role="admin"),
            db,
        )

    assert error.value.status_code == 409
    assert "approved" in error.value.detail