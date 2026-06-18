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
mkwt <branch> [--base <branch>] [--vscode | --no-vscode]
mkwt -h | --help
```

- **`mkwt fix/foo`** — create worktree at `<repo>/.worktrees/fix/foo`. Branch is created from the configured `BASE_BRANCH` if it doesn't exist; checked out if it does.
- **`mkwt fix/foo --base main`** — override `BASE_BRANCH` for this invocation only.
- **`mkwt fix/foo --no-vscode`** — skip opening VS Code for this invocation only.
- **`mkwt fix/foo --vscode`** — open VS Code for this invocation only.
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

# Per-worktree env vars — useful for parallelizing tests across worktrees
# (each worktree gets a different test database). Empty = disabled.
# {n} expands to a stable integer unique per active worktree (1, 2, 3, ...).
WORKTREE_ENV_FILE=".env.worktree"
WORKTREE_ENV=""

# After creating the worktree, whether to open it in VS Code.
# Values: ask (prompt; default), always (open without asking), never (skip silently).
# Override per invocation with --vscode / --no-vscode.
OPEN_IN_VSCODE="ask"
```

To make `--no-vscode` the repo default without changing behavior for anyone else, set:

```bash
OPEN_IN_VSCODE="never"
```

Repos without `OPEN_IN_VSCODE` keep the built-in default: `ask`. You can still override the config for a single command with `--vscode` or `--no-vscode`.

### Per-worktree env vars

Setting `WORKTREE_ENV` makes `mkwt` write env vars into each new worktree, with `{n}` replaced by an integer that is unique among active worktrees. The smallest free integer (≥ 1) is chosen, so removing a worktree frees its slot for the next one.

Example for parallel Rails test databases:

```bash
WORKTREE_ENV='TEST_ENV_NUMBER={n}'
```

#### Two modes — fresh file vs. copy-and-append

**Fresh file (default `WORKTREE_ENV_FILE=".env.worktree"`)**: `mkwt` writes a new file in each worktree. You wire it into your app's env loading:

```ruby
# config/application.rb
Dotenv.load(Rails.root.join('.env.worktree')) if Rails.root.join('.env.worktree').exist?
```

**Copy-and-append (set `WORKTREE_ENV_FILE` to a file that exists in main, e.g. `".env"`)**: `mkwt` copies the file from main into the worktree and appends an mkwt-managed block. Auto-loaded by `dotenv-rails` with no app changes:

```bash
WORKTREE_ENV_FILE=".env"
WORKTREE_ENV='TEST_ENV_NUMBER={n}'
# Important: remove ".env" from SYMLINKS — mkwt errors if both refer to the same file.
SYMLINKS="vendor/bundle .claude/settings.local.json"
```

Generated file:

```
# (everything from main's .env)
SECRET_KEY=...

# === mkwt-managed (do not edit) ===
# mkwt-index: 3
TEST_ENV_NUMBER=3
# === end mkwt-managed ===
```

Caveat: the copy is a snapshot — if you later edit `.env` in main, existing worktrees won't pick up the change.

#### Reference in `database.yml`

```yaml
test:
  database: myapp_test_wt<%= ENV.fetch('TEST_ENV_NUMBER', '0') %>
```

Rails' built-in parallelize (which appends `-0`, `-1`...) still works *within* each worktree.

The wizard auto-detects:

- `BASE_BRANCH` from `origin/HEAD` (falls back to current HEAD).
- `SYMLINKS` based on what exists in the repo: `.env`, `.envrc`, `vendor/bundle` (if `Gemfile`), `node_modules` (if `package.json`), `.claude/settings.local.json`.

It also offers to add `.worktrees/` to `.gitignore`.

## Behavior notes

- **Symlinks are relative**, so the worktrees survive the parent repo being moved or renamed.
- **`mkwt` does not `cd` for you** — child processes can't change the parent shell's directory. Use `cd "$(mkwt …)"` to compose.
- **`POST_CREATE_HOOK`** failures leave the worktree in place but cause `mkwt` to exit non-zero, so `cd "$(mkwt …)"` won't silently land you in a broken setup.
- **Branch names with slashes** are preserved verbatim: `fix/eng-321` → `.worktrees/fix/eng-321`.

## Development

```sh
bash -n bin/mkwt setup.sh tests/test_open_in_vscode_config.sh
bash tests/test_open_in_vscode_config.sh
```

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
