#!/bin/sh
# Every held model file belongs to exactly one package, or is recorded as retired.
#
# A model store drifts from its manifest the moment either is edited by hand.
# This makes the property checkable, and it compares against PACKAGES rather
# than any secondary annotation -- two counts written against review tags during
# development were wrong, one reporting 92 unmanaged files against a true 53.
#
# Set logic, so `comm` does the comparing and yq only extracts. Dependencies are
# yq and coreutils.
#
# Usage: check-packages.sh <config-dir>
#   <config-dir> holds models.manifest.yaml and packages/.
# Exit 1 on an orphan, a package claiming a file that is not held, or a file
# claimed twice. A file with no located source is REPORTED but does not fail.

set -eu

# `comm` compares bytes; `sort` orders by locale. Left to differ, comm rejects
# sort's own output as unsorted -- so both are pinned to the same collation.
LC_ALL=C
export LC_ALL

CONFIG="${1:?usage: check-packages.sh <config-dir>}"
MANIFEST="$CONFIG/models.manifest.yaml"
PKGDIR="$CONFIG/packages"

[ -f "$MANIFEST" ] || { echo "no manifest: $MANIFEST" >&2; exit 2; }
[ -d "$PKGDIR" ]   || { echo "no packages dir: $PKGDIR" >&2; exit 2; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# What the store holds, per the audit's manifest.
yq -r '.models[] | select(.paths != null) | .paths[0].path | sub("^models/"; "")' \
  "$MANIFEST" | sort -u > "$work/held"

# What the packages claim. A package marked `references_only` SELECTS files that
# other packages own -- a validation subset picking one file per failure mode,
# say -- so counting its entries as claims would make every one of them look
# claimed twice, which is a modelling error rather than a finding.
: > "$work/claims"
: > "$work/nosource"
: > "$work/nopath"
for pkg in "$PKGDIR"/*.yaml; do
  [ -f "$pkg" ] || continue
  if [ "$(yq -r 'has("package")' "$pkg")" != "true" ]; then continue; fi
  if [ "$(yq -r '.references_only // false' "$pkg")" = "true" ]; then continue; fi
  name="$(yq -r '.package' "$pkg")"
  # The package name is joined on in awk rather than inside the expression:
  # mikefarah yq has no --arg (that is jq), and interpolating into the
  # expression string would make a package name a shell-injection surface.
  yq -r '.models[].files[] | (.path // "!NOPATH")' "$pkg" \
    | awk -v p="$name" '{ print $0 "\t" p }' >> "$work/claims"
  yq -r '.models[].files[] | select((.sources // []) | length == 0) | .path // "!NOPATH"' "$pkg" >> "$work/nosource"
done

grep    '^!NOPATH' "$work/claims" | cut -f2 | sort    > "$work/nopath"  || true
grep -v '^!NOPATH' "$work/claims" | cut -f1 | sort    > "$work/claimed"
sort -u "$work/claimed"                               > "$work/claimed_u"

# Deliberately not packaged.
if [ -f "$PKGDIR/retired.yaml" ]; then
  yq -r '.retired[].files[].path' "$PKGDIR/retired.yaml" | sort -u > "$work/retired"
else
  : > "$work/retired"
fi

# Held, unclaimed, and not retired.
comm -23 "$work/held" "$work/claimed_u" | comm -23 - "$work/retired" > "$work/orphans"
# Claimed but not held: a rebuild would fetch something the manifest never described.
comm -13 "$work/held" "$work/claimed_u" > "$work/absent"
# Claimed by more than one package.
uniq -d "$work/claimed" > "$work/twice"

n_orphan=$(wc -l < "$work/orphans")
n_absent=$(wc -l < "$work/absent")
n_twice=$(wc -l < "$work/twice")
n_nopath=$(wc -l < "$work/nopath")
n_nosrc=$(sort -u "$work/nosource" | grep -cv '^$' || true)

echo "held:            $(wc -l < "$work/held")"
echo "packaged:        $(wc -l < "$work/claimed_u")"
echo "retired:         $(wc -l < "$work/retired")"
echo "orphans:         $n_orphan"
echo "claimed-absent:  $n_absent"
echo "claimed-twice:   $n_twice"
echo "entry-no-path:   $n_nopath"
echo "unreconstructible: $n_nosrc (recorded, not a failure)"

sed 's/^/  ORPHAN /' "$work/orphans" | head -20
sed 's/^/  ABSENT /' "$work/absent"  | head -20
sed 's/^/  TWICE  /' "$work/twice"   | head -20
sed 's/^/  NOPATH /' "$work/nopath"  | head -20

[ "$n_orphan" = 0 ] && [ "$n_absent" = 0 ] && [ "$n_twice" = 0 ] && [ "$n_nopath" = 0 ]
