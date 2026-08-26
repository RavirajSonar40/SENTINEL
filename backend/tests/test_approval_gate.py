"""Tests for the human approval gate before PR creation."""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.routes.remediation import generate_draft_pr


@pytest.mark.asyncio
async def test_generate_pr_rejects_unapproved_fix():
    fix = MagicMock(status="generated")
    investigation = MagicMock()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [fix, investigation]

    with pytest.raises(HTTPException) as error:
        await generate_draft_pr(
            MagicMock(investigation_id="investigation", fix_id="fix", branch_name=None),
            MagicMock(),
            db,
        )

    assert error.value.status_code == 409
    assert "approved" in error.value.detail