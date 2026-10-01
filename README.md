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

`mkwt --version` reports the executable version and source revision. The installer
embeds the checkout revision, so it still works after the source checkout is
removed. A modified checkout reports a `-dirty` suffix. Source archives without
Git metadata report `unknown` for the revision; install from a pinned Git checkout
when the source revision needs to be verified. `MKWT_INSTALL_DIR` overrides the
installation directory; its default remains `~/.local/bin`.

The original human workflow is preserved in the
[v0.1.0 release](https://github.com/EdoMon93/mkwt/releases/tag/v0.1.0). To install
that baseline in a separate source checkout:

```sh
git clone --branch v0.1.0 --depth 1 https://github.com/EdoMon93/mkwt.git mkwt-v0.1.0
cd mkwt-v0.1.0
./setup.sh
```

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

## Automation

The ordinary `mkwt <branch>` command, repository-local Bash configuration,
automatic fetching, setup wizard, configured setup, VS Code behavior, and plain
path output keep their existing behavior. Automation is selected by its explicit
flags. In particular, `mkwt create` and `mkwt remove` still create branches with
those names; adding `--repo`, `--path`, or another automation flag selects the
corresponding operation. Automation requires Bash 4.4+ and Git 2.48+; these new
requirements do not apply to the legacy human workflow. No Python or JSON utility
is required at runtime.

```sh
mkwt create \
  --repo /srv/repos/project \
  --path /srv/workspaces/run-123/claude \
  --commit FULL_COMMIT_SHA \
  --detach \
  --config /etc/orchestrator/mkwt.conf \
  --non-interactive \
  --json

mkwt remove \
  --repo /srv/repos/project \
  --path /srv/workspaces/run-123/claude \
  --non-interactive \
  --json

mkwt --version --json
```

Both lifecycle operations require `--repo`, `--path`, and `--non-interactive`.
Creation additionally requires `--commit`, `--detach`, and `--config`. Only removal
accepts `--force`. Value flags also accept `--flag=value`. Relative repository,
workspace, and config paths are resolved from the invocation's working directory;
workspace paths normalize `.`/`..` and existing directory symlinks. Paths containing
spaces, quotes, tabs, and newlines are supported. JSON assumes UTF-8 path names.
The repository can be a main checkout, linked worktree, or bare repository.

Creation takes a full 40- or 64-character commit object ID, checks that it exists
locally and is a commit, and creates a detached worktree at that exact revision.
It never fetches, including lazy fetching from a partial clone. Existing files,
directories, symlinks, and worktree registrations are collisions and are never
reused or cleaned up. Creation atomically reserves the destination directory so
a racing collision does not imply ownership of another process's files.
If registration succeeds but checkout fails, the worktree
is left for inspection and its surviving state is reported. Parent directories
may remain after a failed operation. mkwt does not roll back or broadly prune.

### External server configuration

Use an explicitly selected readable file, which may live outside the product
repository:

```sh
SYMLINKS=""
WORKTREE_ENV=""
POST_CREATE_HOOK=""
OPEN_IN_VSCODE="never"
```

Automation reads literal assignments, without sourcing or executing the file.
Blank lines, comments, CRLF, and plain unquoted, single-quoted, or double-quoted
values are accepted. Double-quoted values cannot contain shell expansion,
backticks, or escapes. Commands, expansion expressions, and unknown keys fail
with `INVALID_CONFIG`. Existing `BASE_BRANCH`, `WORKTREE_DIR`, and
`WORKTREE_ENV_FILE` literal assignments are accepted but unused by this interface.
The original human configuration still supports executable Bash as before.

`SYMLINKS`, `WORKTREE_ENV`, and `POST_CREATE_HOOK` must be empty or omitted in
unattended creation. This interface performs no additional setup. It writes no
config or `.gitignore`, and does not generate/copy environment files or launch an
editor or VS Code, regardless of `OPEN_IN_VSCODE`. Removal requires no config.

For automation, Git checkout hooks, fsmonitor, automatic maintenance, and
configured clean/smudge/process filters are disabled for the invocation without
changing repository config. This prevents configured subprocesses from prompting,
launching applications, or downloading objects. Git LFS files therefore remain
pointer files; additional preparation belongs to the orchestrator. Commit object
replacement is disabled, and ambient repository-selection environment variables
cannot override `--repo`.

### Removal policy

Removal operates on exactly one registered linked worktree belonging to `--repo`.
It refuses the main checkout, unrelated directories, symlink targets, mismatched
Git metadata, locked worktrees, and registered-but-missing worktrees, even with
`--force`. Repair or unlock those explicitly. If both the directory and its
registration are absent, removal succeeds with `already_absent`.

By default, staged/unstaged changes, untracked files, and **ignored files** all
cause `DIRTY_WORKTREE`. `--force` explicitly permits discarding their contents.
Git may also refuse submodule-containing worktrees without force. Branches are
never deleted. Repository locking, inspection, active-workspace protection, and
retention remain the orchestrator's responsibility.

### JSON and exit contract

With `--json`, stdout contains exactly one JSON object and diagnostics go to
stderr, including validation and runtime failures. Without it, successful
lifecycle operations print the absolute path. `--version` prints a version line,
or the same JSON envelope when combined with `--json`.

| Field | Meaning |
|---|---|
| `schema_version` | Integer `1` |
| `operation` | `create`, `remove`, `version`, or the attempted operation on invalid input |
| `status` | `created`, `removed`, `already_absent`, `ok` for version, `error`, or `partial_failure` |
| `workspace_path` | Absolute resolved requested path, or `null` when unknown/not applicable |
| `head_sha` | Actual full HEAD, captured before successful removal; `null` if unknown |
| `branch` | Attached branch name, or `null` |
| `detached` | `true`, `false`, or `null` when unknown |
| `path_exists` | Whether the workspace exists at reporting time |
| `worktree_registered` | Whether it remains registered in the specified repository |
| `created_this_invocation` | Whether this creation left a directory or registration after preflight |
| `surviving_path` | Path left by this creation, or `null`; collisions do not claim ownership |
| `version` | Executable version identifier |
| `source_revision` | Embedded/source Git revision, possibly `-dirty` or `unknown` |
| `error` | `null`, or an object with stable `code` and human-readable `message` |

Exit status is `0` for success, including repeated removal, and `1` for errors or
partial failure. Stable codes are `INVALID_ARGUMENTS`, `INVALID_REPOSITORY`,
`INVALID_PATH`, `CONFIG_NOT_FOUND`, `INVALID_CONFIG`, `UNSUPPORTED_BASH`,
`UNSUPPORTED_GIT`, `COMMIT_UNAVAILABLE`, `NOT_A_COMMIT`, `PATH_COLLISION`,
`CREATE_FAILED`, `CHECKOUT_FAILED`, `HEAD_MISMATCH`, `MAIN_WORKTREE`,
`NOT_REGISTERED`, `STALE_REGISTRATION`, `WORKTREE_LOCKED`, `DIRTY_WORKTREE`,
`INSPECTION_FAILED`, `REMOVE_FAILED`, `INTERNAL_ERROR`, and `INTERRUPTED`.
Messages are diagnostic text, not identifiers for parsing. Process termination,
output write failure, or SIGKILL may prevent a result from being emitted. Inspect
the workspace/registration after an interrupted invocation rather than assuming
it completed.

## Development

```sh
bash -n bin/mkwt setup.sh tests/test_open_in_vscode_config.sh
bash tests/test_open_in_vscode_config.sh
python3 -m unittest discover -s tests -p test_automation.py
```

Python 3.8+ is needed only for the integration tests. They create disposable Git
repositories and verify automation, partial clones/failures, removal safety,
legacy branch names/VS Code launches, and installed version metadata.

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
