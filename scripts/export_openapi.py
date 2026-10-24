"""Write the OpenAPI document to packages/contracts/openapi.json (used to generate the TS client)."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
os.environ.setdefault("TASK_EXECUTION", "manual")

from aseo.api.app import create_app  # noqa: E402

spec = create_app(start_background=False).openapi()
out = ROOT / "packages/contracts/openapi.json"
out.write_text(json.dumps(spec, indent=2))
print(f"wrote {out} ({len(spec['paths'])} paths)")
