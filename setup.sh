#!/usr/bin/env bash
# setup.sh — install or update mkwt at ~/.local/bin/mkwt
#
# Re-running this script updates the installed binary in place. To pick up
# upstream changes: `git pull` in this repo, then `./setup.sh`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/bin/mkwt"
INSTALL_DIR="$HOME/.local/bin"
DEST="$INSTALL_DIR/mkwt"

if [[ ! -f "$SRC" ]]; then
  echo "setup.sh: cannot find $SRC — run from inside the mkwt repo" >&2
  exit 1
fi

mkdir -p "$INSTALL_DIR"

if [[ -e "$DEST" ]]; then
  if cmp -s "$SRC" "$DEST"; then
    echo "mkwt is already up to date at $DEST"
  else
    install -m 0755 "$SRC" "$DEST"
    echo "Updated mkwt → $DEST"
  fi
else
  install -m 0755 "$SRC" "$DEST"
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
