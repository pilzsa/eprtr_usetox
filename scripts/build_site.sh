#!/usr/bin/env bash
# Render the whole atlas locally, exactly as CI does.
#
#   scripts/build_site.sh          # check tokens, stage dashboard, render
#   scripts/build_site.sh --serve  # ... then serve http://localhost:8000
#
# The data scripts (build_dataset / build_permits / population_profile /
# build_findings) are not run here: they need the multi-gigabyte EEA and JRC
# inputs.  Their outputs are committed.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

python3 analysis/check_tokens.py
# substances.json is derived from the committed releases/*.json only, so it can
# be rebuilt here (unlike build_dataset.py, which needs the EEA inputs).
python3 analysis/build_substances.py
chmod +x scripts/stage_web.sh
quarto render analysis --to html
rm -rf analysis/_site/.quarto analysis/_site/outputs
touch analysis/_site/.nojekyll

printf 'site: %s\n' "$root/analysis/_site"
du -sh analysis/_site

if [[ "${1:-}" == "--serve" ]]; then
  cd analysis/_site
  exec python3 -m http.server 8000
fi
