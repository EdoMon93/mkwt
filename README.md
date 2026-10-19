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

To pin v0.4.0 after it is tagged:

```sh
git clone --branch v0.4.0 --depth 1 https://github.com/EdoMon93/mkwt.git mkwt-v0.4.0
cd mkwt-v0.4.0
./setup.sh
mkwt --version
```

The executable reports version `0.4.0` and its source revision. This release
adds adoption of existing linked worktrees and skips numeric slots for templates
without `{n}`. It retains caller-supplied identities, private env generation, and
preserves `mkwt <branch>` and the configured VS Code workflow. The explicit
[automation commands](#automation) require Bash 4.4+ and Git 2.48+.
Pinned checkouts stay at that release; use a new tagged checkout to upgrade.

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

Setting `WORKTREE_ENV` makes `mkwt` write env vars into each new worktree, with `{n}` replaced by an integer that is unique among active worktrees. The smallest free integer (≥ 1) is chosen, so removing a worktree frees its slot for the next one. `{id}` expands to the same number in the human workflow. New worktrees also record their identity and numeric slot in their Git registration, so deleting an env file or changing its configured filename does not free the slot. See the [locking contract](#identity-allocation-and-locking) when mixing human and unattended creation.

Example for parallel Rails test databases:

```bash
WORKTREE_ENV='TEST_ENV_NUMBER={n}'
```

The copy-and-append behavior below applies to the human workflow. Unattended
creation always writes a fresh private file and never copies a main checkout env file.

#### Two modes — fresh file vs. copy-and-append

**Fresh file (default `WORKTREE_ENV_FILE=".env.worktree"`)**: `mkwt` writes a new file in each worktree. With dotenv-rails 3.x, load it inside the application class in `config/application.rb`, before code that reads these variables:

```ruby
Dotenv.load(Rails.root.join('.env.worktree'), overwrite: true)
```

`Dotenv.overload(Rails.root.join('.env.worktree'))` is equivalent. Ordinary
`Dotenv.load` preserves existing `ENV` values. By the time the application class
body runs, dotenv-rails has loaded `.env`, so a plain load would silently preserve
its `DATABASE_NAME`. Explicit overwrite also replaces values inherited from the
shell. See the [dotenv API](https://github.com/bkeepers/dotenv/blob/v3.1.8/lib/dotenv.rb)
and [Rails loading callback](https://github.com/bkeepers/dotenv/blob/v3.1.8/lib/dotenv/rails.rb).

Alternatively, generate `.env.development.local`, which dotenv-rails loads before
`.env.development` and `.env`. Existing shell values still take precedence.
With `RAILS_ENV=test`, it loads `.env.test.local`, `.env.test`, then `.env`;
neither `.env.development.local` nor `.env.local` is loaded. To share one generated
file between development and test, the caller can create this symlink inside the
worktree after generation:

```sh
ln -s .env.development.local .env.test.local
```

Or explicitly load `.env.development.local` with `overwrite: true` in the
application class for both environments. See the [dotenv 3.x precedence docs](https://github.com/bkeepers/dotenv/blob/v3.2.0/README.md#customizing-rails).
Keep generated local files out of version control. `mkwt adopt` never creates
this symlink itself.

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
flags. In particular, `mkwt create`, `mkwt adopt`, and `mkwt remove` still create branches with
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
  --worktree-id 5f38b9a814f348dfab1a39945fd574d0 \
  --non-interactive \
  --json

mkwt adopt \
  --repo /srv/repos/project \
  --path /home/t3/.t3/worktrees/project/run-123 \
  --config /etc/orchestrator/mkwt.conf \
  --worktree-id a82c4d9e10 \
  --non-interactive \
  --json

mkwt remove \
  --repo /srv/repos/project \
  --path /srv/workspaces/run-123/claude \
  --non-interactive \
  --json

mkwt --version --json
```

All three operations require `--repo`, `--path`, and `--non-interactive`.
Creation additionally requires `--commit`, `--detach`, and `--config`, and accepts
optional `--worktree-id`. Adoption requires `--config` and `--worktree-id`, and
rejects `--commit`, `--detach`, and `--force`. Removal rejects `--worktree-id`. Only removal
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

### Adopt an existing worktree

`adopt` configures a linked worktree that Git or T3 Code already created and
registered in `--repo`. It shares removal's validation and refuses the main
checkout, unregistered or missing paths, symlink targets, locked worktrees, and
mismatched Git metadata. Absolute and relative Git registration paths are
supported. It records the caller's ID and generates the env file
without creating a worktree, checking out files, creating symlinks, or running a
hook. Attached and detached worktrees are supported; existing changes stay intact.

The first successful adoption returns `configured`. A retry returns
`already_configured` only when the stored ID, recorded env path, and exact file
contents match the requested configuration and the file still has mode `0600`.
Changed permissions fail with `ENV_PATH_COLLISION` and are never silently repaired.
Mode inspection uses the standard `ls` utility. The stored numeric slot is reused,
even if a lower slot has become free. Retry validation does not rewrite files or
metadata. A template that generates different bytes, a changed path, a changed
file, a missing file, or a symlink destination fails with `ENV_PATH_COLLISION`.
A different ID on an identified worktree fails with `IDENTITY_FAILED`;
an ID held by another worktree fails with
`DUPLICATE_WORKTREE_ID`. Existing files are never claimed merely because their
contents match. If generation is disabled, retries require the same stored ID
and no recorded env path. A template requiring `{n}` cannot reuse slot `0` and
fails with `IDENTITY_FAILED`.

Initial adoption validates env parents and destination collisions before recording
an identity. Correcting these errors allows a fresh attempt without metadata
repair. Once generation starts, adoption records the intended env path before
writing the file, so an interruption after a complete write can be retried using
the same identity, path, and contents. An incomplete file still fails validation.

T3 can run `adopt` in its project setup script after `git worktree add`. The caller
may derive an ID from the first 10 hex characters of SHA-1 of the worktree path;
mkwt treats it as a literal ID and still checks for duplicates. For example:

```sh
SYMLINKS=""
POST_CREATE_HOOK=""
OPEN_IN_VSCODE="never"
WORKTREE_ENV_FILE=".env.development.local"
WORKTREE_ENV='DATABASE_NAME=engage_dev_{id}
GOODJOB_DATABASE_NAME=goodjob_dev_{id}
TEST_DATABASE_NAME=engage_test_{id}
TEST_GOODJOB_DATABASE_NAME=goodjob_test_{id}'
```

This template reserves no numeric slot. The caller must still hold the
[repository lock](#identity-allocation-and-locking), and must arrange for Rails to
load this file in test too, as described under [fresh files](#two-modes--fresh-file-vs-copy-and-append).

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
values are accepted. Quoted values may span physical lines. Double-quoted values
cannot contain shell expansion, backticks, or escapes. Single-quoted values are
literal, including dollar signs and backticks. Commands outside quoted values,
expansion expressions in double-quoted or unquoted values, and unknown keys fail
with `INVALID_CONFIG`. Diagnostics identify config lines or keys without printing
values. Duplicate assignments use the last value, as in the human configuration.
`BASE_BRANCH` and `WORKTREE_DIR` are accepted but unused by this interface. The
original human configuration still supports executable Bash as before.

`SYMLINKS` and `POST_CREATE_HOOK` must be empty or omitted in unattended creation
and adoption. Neither writes config or `.gitignore` or launches an editor or VS Code,
regardless of `OPEN_IN_VSCODE`. Removal requires no config.

To generate multiple environment assignments, put literal newlines inside one
quoted `WORKTREE_ENV` value:

```sh
SYMLINKS=""
POST_CREATE_HOOK=""
OPEN_IN_VSCODE="never"
WORKTREE_ENV_FILE=".env.worktree"
WORKTREE_ENV='WORKTREE_ID={id}
TEST_ENV_NUMBER={n}'
```

An empty or omitted `WORKTREE_ENV` disables environment generation. The default
filename is `.env.worktree`. `WORKTREE_ENV_FILE` is ignored when generation is
disabled. With generation enabled, the filename must be a nonempty relative
path. Absolute paths, empty components, trailing slashes, `.`, `..`, `.git`
components of any letter case, and control characters are rejected before
generation with `UNSAFE_ENV_PATH`. Every parent must be a real directory, and an
existing destination of any type is refused on initial generation. Symlink parents
and non-directory parents cause `UNSAFE_ENV_PATH`; existing destinations,
including dangling symlinks, cause `ENV_PATH_COLLISION`.

Unattended generation writes a fresh file with mode `0600`. New parent directories
have mode `0700`; existing parents retain their permissions. Files use exclusive
creation and never overwrite checkout content or copy credentials from a main
checkout. The generated file includes the existing `# mkwt-index: N` managed
block. Template values and generated contents never appear in JSON or diagnostics.
For `create`, generation runs after checkout and HEAD verification. For `adopt`,
it runs after verifying the existing registration, preflighting the destination,
and persisting the identity and intended env path.

### Identity allocation and locking

`--worktree-id` accepts exactly 1–128 ASCII characters. The first must be a letter
or digit; the rest may be letters, digits, underscore, dot, or hyphen. Case is
significant. Invalid, empty, or repeated flags fail with `INVALID_ARGUMENTS`.
An explicit ID is stored even when environment generation is disabled. Without
an explicit ID, generation allocates a positive decimal identity automatically;
with neither an explicit ID nor generation, the identity is `null`.

`{id}` substitutes the exact explicit ID or the automatic decimal identity.
`{n}` substitutes a separately allocated positive integer, never a string
ID or a caller-selected port. For explicit IDs, `{n}` uses the smallest available
numeric slot, even when the ID itself is numeric. For automatic IDs, mkwt uses
the smallest slot that is also free as an identity. In unattended `create` and
`adopt`, a numeric slot is allocated only when `WORKTREE_ENV` contains `{n}`.
Otherwise the stored slot and managed `# mkwt-index` marker are `0`, meaning no
slot is reserved. Without an explicit ID, a template without `{n}` still gets the
smallest positive decimal ID not already assigned as an identity. The human
workflow retains its existing numeric allocation behavior.

Identity and numeric-slot metadata lives in the linked worktree's Git registration,
independently of the generated env file. Creation persists it before checkout;
adoption persists it before generation. A checkout or generation failure keeps
the assigned identity reserved. Reusing an identity in another registered
worktree fails with `DUPLICATE_WORKTREE_ID` before creating a destination or
adopting a worktree, regardless of configured env filenames or deleted env files.
Missing and locked worktrees still reserve their identities until their
Git registrations are explicitly removed or pruned. Successful removal releases
the identity. Moving a worktree with `git worktree move` retains it. Do not edit
mkwt's registration metadata. Missing or malformed identity records require
caller-managed inspection and repair; unreadable or malformed records fail
allocation with `IDENTITY_FAILED`.

For worktrees made by older releases, the numeric marker in the currently selected
env filename is still respected. Before changing that filename, remove or recreate
older worktrees whose only identity is in their env file. New human worktrees
record their numeric identities in Git too.

**The caller must serialize all mutations of a repository.** mkwt does not acquire
an internal repository lock. Hold one exclusive lock from before invocation until
it exits, covering allocation, duplicate detection, registration, checkout,
environment generation, and error reporting. Every caller must use the same lock
for the same Git common directory, including callers entering through a bare repo
or another linked worktree. Human creation and direct Git add/remove/move/prune
operations must participate in that lock too. Do not run the app or another writer
in the target checkout during creation or adoption. Allocation and duplicate guarantees
apply under this contract; unsynchronized creation is unsupported. Atomic
reservation still protects destination ownership from incidental path collisions.
Skipping numeric slot allocation does not remove this requirement: duplicate-ID
checks and identity persistence still require the caller-held repository lock.
Hold it for `adopt` retries too. Serialize T3's preceding `git worktree add` using
the same lock, and prevent removal or movement between add and adoption.

For example, if `flock` is available on the caller's host and all callers agree on
the lock path:

```sh
flock /srv/locks/project-worktrees.lock mkwt create \
  --repo /srv/repos/project --path /srv/workspaces/run-123/reviewer \
  --commit FULL_COMMIT_SHA --detach --config /etc/orchestrator/project-mkwt.conf \
  --worktree-id 5f38b9a814f348dfab1a39945fd574d0 --non-interactive --json

flock /srv/locks/project-worktrees.lock mkwt adopt \
  --repo /srv/repos/project --path /home/t3/.t3/worktrees/project/run-123 \
  --config /etc/orchestrator/project-mkwt.conf \
  --worktree-id a82c4d9e10 --non-interactive --json
```

`flock` is a caller option, not an mkwt runtime dependency. Integration tests use
an external exclusive lock around concurrent callers to verify distinct automatic
IDs and rejection of duplicate explicit IDs.

`ENV_GENERATION_FAILED` covers parent-directory creation, exclusive file creation,
writing, and recording the generated path. An incomplete private env file may
survive a write failure. `IDENTITY_FAILED` covers reading or persisting identity
metadata. Errors after creating a directory or registration report
`partial_failure`, `created_this_invocation`, `worktree_registered`, and
`surviving_path` from the surviving state. A successfully persisted identity stays
reserved. On initial generation, `worktree_env_path` is populated only after the
env file was completely written. A recorded path captured on an adoption retry
or removal can still refer to a changed or incomplete file; only a successful
adoption validates it. mkwt does not roll back these failures; inspect the registered worktree
and remove it explicitly for a fresh retry.

An adoption error after identity persistence reports `partial_failure` and keeps
the identity reserved. Because adoption never creates the checkout,
`created_this_invocation` remains `false` and `surviving_path` remains `null`;
`workspace_path`, `path_exists`, and `worktree_registered` describe the existing
worktree. A later retry only succeeds if all identity, path, and content checks
pass. Incomplete metadata or files require caller-managed inspection and repair.

Dependencies, database creation and migrations, application startup, host-wide
port allocation, database isolation verification, and database cleanup belong to
the orchestrator.

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
| `operation` | `create`, `adopt`, `remove`, `version`, or the attempted operation on invalid input |
| `status` | `created`, `configured`, `already_configured`, `removed`, `already_absent`, `ok` for version, `error`, or `partial_failure` |
| `workspace_path` | Absolute resolved requested path, or `null` when unknown/not applicable |
| `head_sha` | Actual full HEAD, captured before successful removal; `null` if unknown |
| `branch` | Attached branch name, or `null` |
| `detached` | `true`, `false`, or `null` when unknown |
| `path_exists` | Whether the workspace exists at reporting time |
| `worktree_registered` | Whether it remains registered in the specified repository |
| `created_this_invocation` | Whether this creation left a directory or registration after preflight |
| `surviving_path` | Path left by this creation, or `null`; collisions do not claim ownership |
| `worktree_id` | Persisted identity for create/adopt, or identity captured before removal; `null` when not assigned or unknown |
| `worktree_env_path` | Absolute fully generated env-file path, or the recorded path captured on adopt/remove; `null` when disabled, incomplete, or unknown |
| `version` | Executable version identifier |
| `source_revision` | Embedded/source Git revision, possibly `-dirty` or `unknown` |
| `error` | `null`, or an object with stable `code` and human-readable `message` |

The v0.3.0 fields `worktree_id` and `worktree_env_path` are additive.
`schema_version` remains `1`; clients must allow additional fields. Version
responses and operations without identity metadata use `null` for both fields.

Exit status is `0` for success, including repeated adoption or removal, and `1` for errors or
partial failure. Stable codes are `INVALID_ARGUMENTS`, `INVALID_REPOSITORY`,
`INVALID_PATH`, `CONFIG_NOT_FOUND`, `INVALID_CONFIG`, `UNSUPPORTED_BASH`,
`UNSUPPORTED_GIT`, `COMMIT_UNAVAILABLE`, `NOT_A_COMMIT`, `PATH_COLLISION`,
`CREATE_FAILED`, `CHECKOUT_FAILED`, `HEAD_MISMATCH`, `MAIN_WORKTREE`,
`NOT_REGISTERED`, `STALE_REGISTRATION`, `WORKTREE_LOCKED`, `DIRTY_WORKTREE`,
`INSPECTION_FAILED`, `REMOVE_FAILED`, `INTERNAL_ERROR`, `INTERRUPTED`,
`DUPLICATE_WORKTREE_ID`, `IDENTITY_FAILED`, `UNSAFE_ENV_PATH`,
`ENV_PATH_COLLISION`, and `ENV_GENERATION_FAILED`.
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
