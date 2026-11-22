"""Write docs/packwright.schema.json from the packwright.toml model.

    uv run python scripts/gen_packwright_schema.py

Editors read it through Taplo (Even Better TOML in VS Code) when packwright.toml
starts with ``#:schema <url>``. A unit test (TC-PWT-015) fails while the committed
file differs from what the model generates.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.packwright_toml import json_schema  # noqa: E402

out = ROOT / "docs" / "packwright.schema.json"
out.write_text(json.dumps(json_schema(), indent=2) + "\n", encoding="utf-8")
print(f"wrote {out.relative_to(ROOT)}")
