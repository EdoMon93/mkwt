# mkwt

Create a git worktree with configurable symlinks from the main checkout, in one command.

```sh
mkwt fix/eng-321-foo
# Worktree ready at /path/to/repo/.worktrees/fix/eng-321-foo

cd "$(mkwt fix/eng-321-foo)"
```

## Install

```sh
git clone <this-repo> ~/mkwt
cd ~/mkwt
./setup.sh
```

`setup.sh` installs `mkwt` to `~/.local/bin/mkwt`. If `~/.local/bin` is not on your `$PATH`, the script prints the line to add to `~/.bashrc` or `~/.zshrc`.

## Update

```sh
cd ~/mkwt
git pull
./setup.sh
```

`setup.sh` is idempotent — re-running it overwrites the installed binary with the current source.

## Usage

```
mkwt <branch> [--base <branch>]
mkwt -h | --help
```

- **`mkwt fix/foo`** — create worktree at `<repo>/.worktrees/fix/foo`. Branch is created from the configured `BASE_BRANCH` if it doesn't exist; checked out if it does.
- **`mkwt fix/foo --base main`** — override `BASE_BRANCH` for this invocation only.
- **stdout** is the absolute path to the new worktree (composable with `cd`).
- **stderr** is progress + a final `cd` hint.

## Config

On first use in a repo, `mkwt` runs an interactive wizard that auto-detects sensible defaults and writes `.worktrees/mkwt.conf`. Re-run the wizard anytime by deleting that file.

The config is a bash-sourceable file:

```bash
# .worktrees/mkwt.conf

# Paths to symlink from main checkout into each new worktree.
# Missing sources are warned and skipped.
SYMLINKS=".env vendor/bundle"

# Where worktrees live, relative to repo root.
WORKTREE_DIR=".worktrees"

# Default base branch when creating a new branch.
BASE_BRANCH="development"

# Optional command run via 'bash -c' inside the new worktree after creation.
POST_CREATE_HOOK="bundle install"
```

The wizard auto-detects:

- `BASE_BRANCH` from `origin/HEAD` (falls back to current HEAD).
- `SYMLINKS` based on what exists in the repo: `.env`, `.envrc`, `vendor/bundle` (if `Gemfile`), `node_modules` (if `package.json`).

It also offers to add `.worktrees/` to `.gitignore`.

## Behavior notes

- **Symlinks are relative**, so the worktrees survive the parent repo being moved or renamed.
- **`mkwt` does not `cd` for you** — child processes can't change the parent shell's directory. Use `cd "$(mkwt …)"` to compose.
- **`POST_CREATE_HOOK`** failures leave the worktree in place but cause `mkwt` to exit non-zero, so `cd "$(mkwt …)"` won't silently land you in a broken setup.
- **Branch names with slashes** are preserved verbatim: `fix/eng-321` → `.worktrees/fix/eng-321`.

## Errors

| Scenario | Behavior |
|---|---|
| Not inside a git repo | Fails fast |
| Branch already checked out elsewhere | Fails with git's error + hint |
| `BASE_BRANCH` (or `--base`) doesn't exist | Fails before creating anything |
| Worktree path already exists or is registered | Fails — does not auto-clean |
| Symlink source missing | Warns, skips, continues |
| `git fetch` fails (offline, no remote) | Warns, continues |
| `POST_CREATE_HOOK` fails | Warns, leaves worktree, exits non-zero |
