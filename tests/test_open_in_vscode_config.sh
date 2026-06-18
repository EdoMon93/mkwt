#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MKWT="$ROOT/bin/mkwt"
README="$ROOT/README.md"
TMP_DIRS=()
trap 'for dir in "${TMP_DIRS[@]}"; do rm -rf "$dir"; done' EXIT

fail() {
  printf 'not ok - %s\n' "$*" >&2
  exit 1
}

assert_file_missing() {
  local path="$1"
  [[ ! -e "$path" ]] || fail "expected $path to be missing"
}

assert_file_exists() {
  local path="$1"
  [[ -e "$path" ]] || fail "expected $path to exist"
}

assert_grep() {
  local pattern="$1"
  local path="$2"
  grep -Eq -- "$pattern" "$path" || fail "expected $path to match $pattern"
}

make_repo() {
  local repo="$1"
  local open_in_vscode="$2"

  git init -b main "$repo" >/dev/null
  git -C "$repo" config user.email test@example.com
  git -C "$repo" config user.name 'mkwt test'
  git -C "$repo" commit --allow-empty -m 'initial commit' >/dev/null

  mkdir -p "$repo/.worktrees"
  cat > "$repo/.worktrees/mkwt.conf" <<EOF_CONFIG
SYMLINKS=""
WORKTREE_DIR=".worktrees"
BASE_BRANCH="main"
POST_CREATE_HOOK=""
WORKTREE_ENV_FILE=".env.worktree"
WORKTREE_ENV=""
OPEN_IN_VSCODE="$open_in_vscode"
EOF_CONFIG
}

run_with_fake_code() {
  local repo="$1"
  local branch="$2"
  local code_log="$3"
  shift 3

  local fake_bin="$repo/fake-bin"
  mkdir -p "$fake_bin"
  cat > "$fake_bin/code" <<EOF_CODE
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$code_log"
EOF_CODE
  chmod +x "$fake_bin/code"

  (
    cd "$repo"
    PATH="$fake_bin:$PATH" "$MKWT" "$branch" "$@" </dev/null >"$repo/mkwt.stdout" 2>"$repo/mkwt.stderr"
  )
}

test_readme_documents_open_in_vscode_config() {
  assert_grep 'OPEN_IN_VSCODE="never"' "$README"
  assert_grep '--vscode / --no-vscode' "$README"
}

test_config_never_skips_vscode_without_flag() {
  local tmp repo code_log
  tmp="$(mktemp -d)"
  TMP_DIRS+=("$tmp")
  repo="$tmp/repo"
  code_log="$tmp/code.log"

  make_repo "$repo" never
  run_with_fake_code "$repo" feature/no-vscode-default "$code_log"

  assert_file_missing "$code_log"
  assert_file_exists "$repo/.worktrees/feature/no-vscode-default/.git"
}

test_vscode_flag_overrides_config_never() {
  local tmp repo code_log
  tmp="$(mktemp -d)"
  TMP_DIRS+=("$tmp")
  repo="$tmp/repo"
  code_log="$tmp/code.log"

  make_repo "$repo" never
  run_with_fake_code "$repo" feature/force-vscode "$code_log" --vscode

  assert_file_exists "$code_log"
  assert_grep '.worktrees/feature/force-vscode' "$code_log"
}

test_config_always_launches_vscode_without_flag() {
  local tmp repo code_log
  tmp="$(mktemp -d)"
  TMP_DIRS+=("$tmp")
  repo="$tmp/repo"
  code_log="$tmp/code.log"

  make_repo "$repo" always
  run_with_fake_code "$repo" feature/always-vscode "$code_log"

  assert_file_exists "$code_log"
  assert_grep '.worktrees/feature/always-vscode' "$code_log"
}

main() {
  local test
  for test in \
    test_readme_documents_open_in_vscode_config \
    test_config_never_skips_vscode_without_flag \
    test_vscode_flag_overrides_config_never \
    test_config_always_launches_vscode_without_flag
  do
    "$test"
    printf 'ok - %s\n' "$test"
  done
}

main "$@"
