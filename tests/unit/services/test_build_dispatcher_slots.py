"""
Tests for counting the builds that hold a build slot.
Source: app/services/build_dispatcher.py (_holding_slot, builds_in_slot)

The Nuitka worker divides the cores by this count, so it has to come back down
however a build ends; a count that only grows would starve every later build.
"""

import pytest

from app.services import build_dispatcher


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_slot_001_count_follows_the_slot():
    """TC-SLOT-001: counted while inside, released after, nested builds add up."""
    before = build_dispatcher.builds_in_slot()
    async with build_dispatcher._holding_slot():
        async with build_dispatcher._holding_slot():
            assert build_dispatcher.builds_in_slot() == before + 2
        assert build_dispatcher.builds_in_slot() == before + 1
    assert build_dispatcher.builds_in_slot() == before


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_slot_002_a_failed_build_gives_its_share_back():
    """TC-SLOT-002: a build that raises is no longer counted."""
    before = build_dispatcher.builds_in_slot()
    with pytest.raises(RuntimeError):
        async with build_dispatcher._holding_slot():
            raise RuntimeError("compile failed")
    assert build_dispatcher.builds_in_slot() == before
