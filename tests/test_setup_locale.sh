#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LOCALE_FIXTURE=$(mktemp)
trap 'rm -f "$LOCALE_FIXTURE"' EXIT

printf 'LANG="tr_TR.UTF-8"\n' > "$LOCALE_FIXTURE"
[[ $(SYSTEM_LOCALE_FILE="$LOCALE_FIXTURE" bash "$ROOT/setup.sh" --print-language) == "tr" ]]

printf 'LANG=en_US.UTF-8\n' > "$LOCALE_FIXTURE"
[[ $(SYSTEM_LOCALE_FILE="$LOCALE_FIXTURE" bash "$ROOT/setup.sh" --print-language) == "en" ]]

printf "LANG='tr_TR.UTF-8'\n" > "$LOCALE_FIXTURE"
[[ $(SYSTEM_LOCALE_FILE="$LOCALE_FIXTURE" bash "$ROOT/setup.sh" --print-language) == "tr" ]]

echo "Setup locale detection tests passed."
