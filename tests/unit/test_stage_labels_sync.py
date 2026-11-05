"""
The console's stage labels must cover every build stage the backend explains.
Source: frontend/src/components/build/stages.ts vs app/services/error_diagnosis._STAGE_HINTS

When the frontend and Docker steps got their own stage on the backend, the
console had no label for them and showed the raw key ("frontend") on the
failure report. Nothing failed — so make the drift fail here instead.
"""

import re
from pathlib import Path

import pytest

from app.services.error_diagnosis import _STAGE_HINTS

STAGES_TS = Path(__file__).resolve().parents[2] / "frontend/src/components/build/stages.ts"


@pytest.mark.unit
def test_tc_stg_001_every_backend_stage_has_a_console_label():
    """TC-STG-001: STAGE_LABELS in the console names every stage the backend reports."""
    block = re.search(r"STAGE_LABELS[^{]*\{(.*?)\n\}", STAGES_TS.read_text(), re.S)
    assert block, "STAGE_LABELS not found in stages.ts"
    labels = set(re.findall(r"^\s*(\w+):", block.group(1), re.M))
    assert set(_STAGE_HINTS) <= labels, f"no console label for: {sorted(set(_STAGE_HINTS) - labels)}"
