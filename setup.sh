#!/usr/bin/env bash
# setup.sh — install or update mkwt at ~/.local/bin/mkwt
#
# Re-running this script updates the installed binary in place. To pick up
# upstream changes: `git pull` in this repo, then `./setup.sh`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/bin/mkwt"
INSTALL_DIR="${MKWT_INSTALL_DIR:-$HOME/.local/bin}"
DEST="$INSTALL_DIR/mkwt"

if [[ ! -f "$SRC" ]]; then
  echo "setup.sh: cannot find $SRC — run from inside the mkwt repo" >&2
  exit 1
fi

mkdir -p "$INSTALL_DIR"

BUILD="$(mktemp)"
trap 'rm -f "$BUILD"' EXIT
SOURCE_REVISION=unknown
if [[ -e "$SCRIPT_DIR/.git" ]]; then
  SOURCE_REVISION="$(git -C "$SCRIPT_DIR" rev-parse HEAD 2>/dev/null || printf unknown)"
  if [[ -n "$(git -C "$SCRIPT_DIR" status --porcelain 2>/dev/null)" ]]; then
    SOURCE_REVISION="$SOURCE_REVISION-dirty"
  fi
fi
sed "s/^MKWT_SOURCE_REVISION=\"source\"$/MKWT_SOURCE_REVISION=\"$SOURCE_REVISION\"/" "$SRC" > "$BUILD"

if [[ -e "$DEST" ]]; then
  if cmp -s "$BUILD" "$DEST"; then
    echo "mkwt is already up to date at $DEST"
  else
    install -m 0755 "$BUILD" "$DEST"
    echo "Updated mkwt → $DEST"
  fi
else
  install -m 0755 "$BUILD" "$DEST"
  echo "Installed mkwt → $DEST"
fi

case ":$PATH:" in
  *":$INSTALL_DIR:"*)
    echo "$INSTALL_DIR is on \$PATH — run 'mkwt --help' to verify."
    ;;
  *)
    cat <<EOF

$INSTALL_DIR is NOT on your \$PATH.

Add this line to your shell rc (~/.bashrc or ~/.zshrc):

    export PATH="\$HOME/.local/bin:\$PATH"

Then reload: 'exec \$SHELL -l' (or open a new terminal).
EOF
    ;;
esac
