#!/usr/bin/env bash
# Stage the dashboard (static frontend + JSON data) into the Quarto site tree.
#
# Both locally and on GitHub Pages the dashboard ends up under /map/, so the
# same relative URLs work in preview (`quarto preview analysis`) and in
# production (https://<owner>.github.io/eprtr_usetox/map/frontend/).
#
# The staged tree is gitignored; `quarto render analysis` copies it into
# `analysis/_site/map/` because `analysis/map` is listed under `resources:`.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest="$root/analysis/map"

rm -rf "$dest"
mkdir -p "$dest"
cp -R "$root/dashboard/frontend" "$dest/frontend"
cp -R "$root/dashboard/data" "$dest/data"

printf 'staged dashboard -> %s\n' "$dest"
du -sh "$dest"
