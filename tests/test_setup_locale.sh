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

grep -q 'CREATE DATABASE IF NOT EXISTS' "$ROOT/setup.sh"
grep -q 'CREATE USER IF NOT EXISTS' "$ROOT/setup.sh"
grep -q 'HAS_EXISTING_CONFIG' "$ROOT/setup.sh"
grep -q 'systemctl restart zimbra-migration' "$ROOT/setup.sh"
echo "Setup repeatability guards are present."

for VALID_USERNAME in admin Migration2026 User123; do
  bash "$ROOT/setup.sh" --validate-username "$VALID_USERNAME"
done
for INVALID_USERNAME in 'invalid user' 'Migration2026-' 'user.name' 'user_name' 'kullanıcı'; do
  if bash "$ROOT/setup.sh" --validate-username "$INVALID_USERNAME"; then
    echo "Invalid username was accepted: $INVALID_USERNAME" >&2
    exit 1
  fi
done
echo "Setup username validation tests passed."
