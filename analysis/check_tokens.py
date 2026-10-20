"""Check that every colour on `styles.qmd` exists in the design tokens.

The design page is the human-readable contract; `tokens.css` and
`tokens-dark.css` are the machine-readable one.  A typo in either would let
the site and the dashboard drift apart silently, so the site build runs this
script before rendering.

Exit code 1 (and the offending hex values) if a swatch is not defined.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "analysis" / "styles.qmd"
TOKENS = [ROOT / "dashboard" / "frontend" / "tokens.css",
          ROOT / "dashboard" / "frontend" / "tokens-dark.css"]
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def main() -> int:
    if not PAGE.exists():
        print(f"missing {PAGE}", file=sys.stderr)
        return 1
    page_hex = {value.lower() for value in HEX.findall(PAGE.read_text(encoding="utf-8"))}
    token_text = "\n".join(path.read_text(encoding="utf-8") for path in TOKENS if path.exists())
    token_hex = {value.lower() for value in HEX.findall(token_text)}
    missing = sorted(page_hex - token_hex)
    if missing:
        print(f"{len(missing)} colour(s) on styles.qmd are not in tokens.css/tokens-dark.css:",
              file=sys.stderr)
        for value in missing:
            print(f"  {value}", file=sys.stderr)
        return 1
    print(f"tokens OK: {len(page_hex)} colours on styles.qmd all defined ({len(token_hex)} tokens)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
