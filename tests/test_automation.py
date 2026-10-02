import json
import concurrent.futures
import fcntl
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MKWT = ROOT / "bin" / "mkwt"


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mkwt-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith("GIT_"):
                del self.env[key]
        self.env["GIT_CONFIG_GLOBAL"] = os.devnull
        self.env["GIT_CONFIG_NOSYSTEM"] = "1"
        self.repo = self.root / "repo with spaces"
        self.git("init", "-b", "main", str(self.repo), cwd=self.root)
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        (self.repo / "tracked.txt").write_text("original\n")
        (self.repo / ".gitignore").write_text("ignored/\n")
        self.git("add", ".")
        self.git("commit", "-m", "initial")
        self.sha = self.git("rev-parse", "HEAD").stdout.strip()
        self.config = self.root / "external config.conf"
        self.config.write_text(
            'SYMLINKS=""\nWORKTREE_ENV=""\nPOST_CREATE_HOOK=""\n'
            'OPEN_IN_VSCODE="always"\n'
        )
        self.workspace = self.root / "workspaces" / "agent with spaces"

    def git(self, *args, cwd=None, check=True):
        return subprocess.run(
            ["git", *args], cwd=cwd or self.repo, text=True,
            capture_output=True, check=check, timeout=15, env=self.env,
        )

    def invoke(self, *args, closed=False, cwd=None, executable=MKWT):
        command = [str(executable), *map(str, args)]
        if closed:
            command = ["bash", "-c", 'exec "$@" 0<&-', "mkwt-test", *command]
        result = subprocess.run(
            command, cwd=cwd or self.root, env=self.env,
            stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=15,
        )
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            self.fail(f"Expected one JSON object: {result.stdout!r}; stderr={result.stderr!r}")
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["schema_version"], 1)
        return result, payload

    def create(self, path=None, sha=None, worktree_id=None, **kwargs):
        extra = [] if worktree_id is None else ["--worktree-id", worktree_id]
        return self.invoke(
            "create", "--repo", self.repo, "--path", path or self.workspace,
            "--commit", sha or self.sha, "--detach", "--config", self.config,
            "--non-interactive", "--json", *extra, **kwargs,
        )

    def remove(self, path=None, force=False, repo=None):
        args = ["remove", "--repo", repo or self.repo, "--path", path or self.workspace,
                "--non-interactive", "--json"]
        if force:
            args.append("--force")
        return self.invoke(*args)

    def assert_error(self, outcome, code, status="error"):
        result, payload = outcome
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["status"], status)
        self.assertEqual(payload["error"]["code"], code)
        self.assertTrue(payload["error"]["message"])
        return payload

    def test_two_detached_worktrees_same_sha_and_closed_stdin(self):
        for path in (self.workspace, self.root / "codex"):
            result, payload = self.create(path=path, closed=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["status"], "created")
            self.assertEqual(payload["workspace_path"], str(path))
            self.assertEqual(payload["head_sha"], self.sha)
            self.assertTrue(payload["detached"])
            self.assertIsNone(payload["branch"])
            self.assertTrue(payload["created_this_invocation"])
            self.assertTrue(payload["worktree_registered"])
            self.assertIsNone(payload["error"])
            self.assertEqual(self.git("rev-parse", "HEAD", cwd=path).stdout.strip(), self.sha)
            self.assertEqual(self.git("symbolic-ref", "-q", "HEAD", cwd=path, check=False).returncode, 1)
        self.assertFalse((self.repo / ".worktrees").exists())
        self.assertEqual((self.repo / ".gitignore").read_text(), "ignored/\n")

    def test_missing_commit_and_non_commit_object(self):
        self.assert_error(self.create(sha="f" * len(self.sha)), "COMMIT_UNAVAILABLE")
        blob = self.git("rev-parse", "HEAD:tracked.txt").stdout.strip()
        self.assert_error(self.create(sha=blob), "NOT_A_COMMIT")
        self.assert_error(self.create(sha="main"), "INVALID_ARGUMENTS")
        self.assertFalse(self.workspace.exists())

    def test_missing_invalid_and_executable_config(self):
        self.config.unlink()
        self.assert_error(self.create(), "CONFIG_NOT_FOUND")
        for content in ('SYMLINKS=".env"\n', 'POST_CREATE_HOOK="echo bad"\n',
                        'UNKNOWN=""\n', "BASE_BRANCH='unterminated\n",
                        f'touch "{self.root / "executed"}"\n',
                        f'SYMLINKS="$(touch {self.root / "executed"})"\n'):
            self.config.write_text(content)
            self.assert_error(self.create(), "INVALID_CONFIG")
            self.assertFalse(self.workspace.exists())
            self.assertFalse((self.root / "executed").exists())

    def test_literal_config_comments_crlf_and_equals_flags(self):
        self.config.write_bytes(
            b"# external server configuration\r\nSYMLINKS='' # none\r\n"
            b"WORKTREE_ENV= # none\r\nPOST_CREATE_HOOK=\r\n"
            b"BASE_BRANCH=main\r\nWORKTREE_DIR='.worktrees'\r\n"
            b'WORKTREE_ENV_FILE=".env.worktree"\r\nOPEN_IN_VSCODE=always\r\n'
        )
        result, _ = self.invoke("create", f"--repo={self.repo}", f"--path={self.workspace}",
                                f"--commit={self.sha}", f"--config={self.config}",
                                "--detach", "--non-interactive", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)

    def env_config(self, filename=".env.worktree", template="WORKTREE_ID={id}\nTEST_ENV_NUMBER={n}"):
        self.config.write_text(
            f"SYMLINKS=''\nPOST_CREATE_HOOK=''\nOPEN_IN_VSCODE=never\n"
            f"WORKTREE_ENV_FILE='{filename}'\nWORKTREE_ENV='{template}'\n"
        )

    def test_explicit_identity_private_multiline_env_without_copying_secrets(self):
        self.env_config(filename="config/local.env")
        (self.repo / "config").mkdir()
        (self.repo / "config/local.env").write_text("PERSONAL_SECRET=do-not-copy\n")
        identity = "5f38b9a814f348dfab1a39945fd574d0"
        result, payload = self.create(worktree_id=identity)
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.workspace / "config/local.env"
        self.assertEqual(payload["worktree_id"], identity)
        self.assertEqual(payload["worktree_env_path"], str(target))
        self.assertIn(f"WORKTREE_ID={identity}\nTEST_ENV_NUMBER=1\n", target.read_text())
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
        for output in (target.read_text(), result.stdout, result.stderr):
            self.assertNotIn("PERSONAL_SECRET", output)
        self.assertNotIn("TEST_ENV_NUMBER=", result.stdout + result.stderr)

    def test_automatic_identity_numeric_templates_and_reuse_after_removal(self):
        self.env_config()
        for index in (1, 2):
            path = self.root / f"auto-{index}"
            result, payload = self.create(path=path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["worktree_id"], str(index))
            self.assertIn(f"TEST_ENV_NUMBER={index}\n", (path / ".env.worktree").read_text())
        result, payload = self.remove(path=self.root / "auto-1", force=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["worktree_id"], "1")
        self.assertEqual(payload["worktree_env_path"], str(self.root / "auto-1/.env.worktree"))
        result, payload = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["worktree_id"], "1")

    def test_duplicate_identity_survives_env_changes_and_missing_checkout(self):
        self.env_config()
        result, _ = self.create(worktree_id="same-id")
        self.assertEqual(result.returncode, 0, result.stderr)

        (self.workspace / ".env.worktree").unlink()
        self.env_config(filename="other.env")
        other = self.root / "other"
        payload = self.assert_error(self.create(path=other, worktree_id="same-id"), "DUPLICATE_WORKTREE_ID")
        self.assertFalse(payload["created_this_invocation"])
        self.assertFalse(other.exists())
        shutil.rmtree(self.workspace)
        self.assert_error(self.create(path=other, worktree_id="same-id"), "DUPLICATE_WORKTREE_ID")
        self.git("worktree", "prune", "--expire=now")
        result, _ = self.create(path=other, worktree_id="same-id")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_moved_and_locked_worktree_keeps_identity_across_repository_contexts(self):
        self.env_config()
        result, _ = self.create(worktree_id="fixed")
        self.assertEqual(result.returncode, 0, result.stderr)
        moved = self.root / "moved"
        self.git("worktree", "move", str(self.workspace), str(moved))
        self.git("worktree", "lock", str(moved))
        self.assert_error(self.invoke(
            "create", "--repo", moved, "--path", self.root / "duplicate",
            "--commit", self.sha, "--config", self.config, "--worktree-id", "fixed",
            "--detach", "--non-interactive", "--json",
        ), "DUPLICATE_WORKTREE_ID")
        self.git("worktree", "unlock", str(moved))
        result, payload = self.remove(path=moved, force=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["worktree_id"], "fixed")
        self.assertEqual(payload["worktree_env_path"], str(moved / ".env.worktree"))

    def test_identity_without_environment_and_numeric_id_is_not_numeric_slot(self):
        result, payload = self.create(worktree_id="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["worktree_id"], "1")
        self.assertIsNone(payload["worktree_env_path"])
        self.assert_error(self.create(path=self.root / "duplicate", worktree_id="1"), "DUPLICATE_WORKTREE_ID")
        self.env_config()
        result, payload = self.create(path=self.root / "explicit", worktree_id="999")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TEST_ENV_NUMBER=1\n", (self.root / "explicit/.env.worktree").read_text())
        result, payload = self.create(path=self.root / "auto")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["worktree_id"], "2")

    def test_string_identity_and_numeric_slot_are_independent(self):
        self.env_config()
        result, _ = self.create(worktree_id="string-id")
        self.assertEqual(result.returncode, 0, result.stderr)
        result, _ = self.create(path=self.root / "numeric-id", worktree_id="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TEST_ENV_NUMBER=2", (self.root / "numeric-id/.env.worktree").read_text())

    def test_identity_validation_and_flag_contract(self):
        for identity in ("", "-start", ".hidden", "a/b", "a b", "a\nb", "a" * 129, "é", "$(touch bad)"):
            self.assert_error(self.create(worktree_id=identity), "INVALID_ARGUMENTS")
            self.assertFalse(self.workspace.exists())
        valid = "A" + "_.-z9" * 25
        result, payload = self.invoke(
            "create", f"--repo={self.repo}", f"--path={self.workspace}",
            f"--commit={self.sha}", f"--config={self.config}", f"--worktree-id={valid}",
            "--detach", "--non-interactive", "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["worktree_id"], valid)
        self.assert_error(self.invoke("remove", "--repo", self.repo, "--path", self.workspace,
                                     "--worktree-id", valid, "--non-interactive", "--json"), "INVALID_ARGUMENTS")
        self.assert_error(self.invoke("create", "--worktree-id", "a", "--worktree-id", "b", "--json"),
                          "INVALID_ARGUMENTS")

    def test_environment_paths_and_checkout_collisions(self):
        for filename in ("", "/tmp/outside", "../escape", "a/../escape", "./env", ".git",
                         ".GIT/config", "a//env", "a/", "a\nenv"):
            self.env_config(filename=filename)
            self.assert_error(self.create(), "UNSAFE_ENV_PATH")
            self.assertFalse(self.workspace.exists())
        self.env_config(filename="tracked.txt")
        payload = self.assert_error(self.create(worktree_id="collision"), "ENV_PATH_COLLISION", "partial_failure")
        self.assertTrue(payload["created_this_invocation"])
        self.assertTrue(payload["worktree_registered"])
        self.assertEqual(payload["surviving_path"], str(self.workspace))
        self.assertEqual(payload["worktree_id"], "collision")
        self.assertIsNone(payload["worktree_env_path"])
        self.assertEqual((self.workspace / "tracked.txt").read_text(), "original\n")
        self.assert_error(self.create(path=self.root / "dup", worktree_id="collision"), "DUPLICATE_WORKTREE_ID")

    def test_environment_refuses_parent_and_destination_symlinks(self):
        outside = self.root / "outside"
        outside.mkdir()
        for name, destination in (("linked", outside), ("dangling", self.root / "missing")):
            (self.repo / name).symlink_to(destination)
        self.git("add", "linked", "dangling")
        self.git("commit", "-m", "symlinks")
        self.sha = self.git("rev-parse", "HEAD").stdout.strip()
        for index, filename in enumerate(("linked/local.env", "linked", "dangling", "dangling/local.env", "tracked.txt/env")):
            self.env_config(filename=filename)
            code = "ENV_PATH_COLLISION" if filename in ("linked", "dangling") else "UNSAFE_ENV_PATH"
            self.assert_error(self.create(path=self.root / f"symlink-{index}"), code, "partial_failure")
        self.assertEqual(list(outside.iterdir()), [])

    def test_generation_failure_keeps_registered_identity_and_private_partial_file(self):
        self.env_config(filename="new/env", template="SECRET=keep-private-{id}")
        fake = self.root / "fake-bin"
        fake.mkdir()
        script = fake / "mkdir"
        script.write_text(
            '#!/bin/sh\ncase "$*" in *new*) exit 9;; esac\n'
            f'exec {shlex.quote(shutil.which("mkdir"))} "$@"\n'
        )
        script.chmod(0o755)
        self.env["PATH"] = str(fake) + os.pathsep + self.env["PATH"]
        result, payload = self.create(worktree_id="failed")
        self.assert_error((result, payload), "ENV_GENERATION_FAILED", "partial_failure")
        self.assertTrue(payload["worktree_registered"])
        self.assertEqual(payload["worktree_id"], "failed")
        self.assertEqual(payload["surviving_path"], str(self.workspace))
        self.assertIsNone(payload["worktree_env_path"])
        self.assertNotIn("keep-private", result.stdout + result.stderr)
        self.assert_error(self.create(path=self.root / "other", worktree_id="failed"), "DUPLICATE_WORKTREE_ID")

    def test_environment_write_failure_is_classified_and_does_not_leak_contents(self):
        self.env_config(template="SECRET=private-value-{id}")
        injected = self.root / "injected.bash"
        injected.write_text(
            "printf() {\n"
            "  if [[ ${1:-} == '# === mkwt-managed'* ]]; then\n"
            "    builtin printf 'partial-private-content\\n'\n    return 9\n  fi\n"
            '  builtin printf "$@"\n}\n'
        )
        self.env["BASH_ENV"] = str(injected)
        result, payload = self.create(worktree_id="write-failed")
        self.assert_error((result, payload), "ENV_GENERATION_FAILED", "partial_failure")
        self.assertTrue(payload["worktree_registered"])
        self.assertEqual(payload["worktree_id"], "write-failed")
        self.assertIsNone(payload["worktree_env_path"])
        target = self.workspace / ".env.worktree"
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.read_text(), "partial-private-content\n")
        for secret in ("private-value", "partial-private-content"):
            self.assertNotIn(secret, result.stdout + result.stderr)

    def test_corrupt_identity_metadata_fails_closed(self):
        self.env_config()
        result, _ = self.create(worktree_id="saved")
        self.assertEqual(result.returncode, 0, result.stderr)
        metadata = Path(self.git("rev-parse", "--absolute-git-dir", cwd=self.workspace).stdout.strip())
        for content in ("", "1\nsaved\n", "1\nsaved\n1\nextra\n"):
            (metadata / "mkwt-identity").write_text(content)
            payload = self.assert_error(self.create(path=self.root / "other"), "IDENTITY_FAILED")
            self.assertFalse(payload["created_this_invocation"])
        (metadata / "mkwt-identity").unlink()
        self.assert_error(self.create(path=self.root / "other"), "IDENTITY_FAILED")

    def test_multiline_config_is_literal_and_unterminated_values_fail(self):
        marker = self.root / "executed"
        self.env_config(template=f"ID={{id}}\nLITERAL=$(touch {marker})\nRAW=`touch {marker}`")
        result, _ = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        self.assertIn("LITERAL=$(touch", (self.workspace / ".env.worktree").read_text())
        self.config.write_text('WORKTREE_ENV="ID={id}\nSECOND={n}" # multiple\n')
        result, _ = self.create(path=self.root / "double")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.config.write_bytes(b"WORKTREE_ENV='ID={id}\r\nSECOND={n}'")
        result, _ = self.create(path=self.root / "crlf")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ID=3\nSECOND=3", (self.root / "crlf/.env.worktree").read_text())
        self.config.write_text('WORKTREE_ENV="ID={id}\nBAD=$HOME"\n')
        self.assert_error(self.create(path=self.root / "bad"), "INVALID_CONFIG")
        self.config.write_text("WORKTREE_ENV='ID={id}\nSECOND={n}\n")
        self.assert_error(self.create(path=self.root / "unclosed"), "INVALID_CONFIG")

    def test_caller_lock_serializes_parallel_allocations_and_duplicate_detection(self):
        self.env_config()
        lock = self.root / "repository.lock"
        def locked_create(index, identity):
            with lock.open("a") as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                return self.create(path=self.root / f"parallel-{index}", worktree_id=identity)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            outcomes = list(executor.map(lambda index: locked_create(index, None), range(4)))
        self.assertEqual({payload["worktree_id"] for _, payload in outcomes}, {"1", "2", "3", "4"})
        for result, _ in outcomes:
            self.assertEqual(result.returncode, 0, result.stderr)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda index: locked_create(index, "shared"), (4, 5)))
        self.assertEqual(sum(result.returncode == 0 for result, _ in outcomes), 1)
        failure = next(outcome for outcome in outcomes if outcome[0].returncode)
        self.assert_error(failure, "DUPLICATE_WORKTREE_ID")

    def test_human_env_copy_append_and_identity_allocation_remain_compatible(self):
        config = self.repo / ".worktrees/mkwt.conf"
        config.parent.mkdir()
        config.write_text("BASE_BRANCH=main\nOPEN_IN_VSCODE=never\nWORKTREE_ENV_FILE=.env\n"
                          "WORKTREE_ENV='HUMAN_ID={id}\nHUMAN_NUMBER={n}'\n")
        (self.repo / ".env").write_text("PERSONAL_SECRET=legacy-copy\n")
        def human_create(branch):
            result = subprocess.run([str(MKWT), branch], cwd=self.repo, env=self.env,
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            return self.repo / ".worktrees" / branch
        first = human_create("human-first")
        self.assertIn("PERSONAL_SECRET=legacy-copy", (first / ".env").read_text())
        self.assertIn("HUMAN_ID=1\nHUMAN_NUMBER=1", (first / ".env").read_text())
        self.env_config()
        result, payload = self.create(worktree_id="automation")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TEST_ENV_NUMBER=2", (self.workspace / ".env.worktree").read_text())
        (self.workspace / ".env.worktree").unlink()
        second = human_create("human-second")
        self.assertIn("HUMAN_ID=3\nHUMAN_NUMBER=3", (second / ".env").read_text())

    def test_legacy_index_markers_are_respected(self):
        legacy = self.root / "legacy"
        self.git("worktree", "add", "--detach", str(legacy), self.sha)
        (legacy / ".env.worktree").write_text("# mkwt-index: 1\nTEST_ENV_NUMBER=1\n")
        self.env_config()
        result, payload = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["worktree_id"], "2")

    def test_empty_config_and_version_have_null_identity_fields(self):
        for outcome in (self.invoke("--version", "--json"), self.create()):
            result, payload = outcome
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNone(payload["worktree_id"])
            self.assertIsNone(payload["worktree_env_path"])

    def test_bare_repository_and_sha256(self):
        bare = self.root / "bare.git"
        self.git("clone", "--bare", str(self.repo), str(bare), cwd=self.root)
        result, payload = self.invoke("create", "--repo", bare, "--path", self.workspace,
                                     "--commit", self.sha, "--config", self.config,
                                     "--detach", "--non-interactive", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["head_sha"], self.sha)
        result, _ = self.remove(repo=bare)
        self.assertEqual(result.returncode, 0, result.stderr)
        sha256 = self.root / "sha256"
        self.git("init", "--object-format=sha256", "-b", "main", str(sha256), cwd=self.root)
        self.git("config", "user.name", "Test", cwd=sha256)
        self.git("config", "user.email", "test@example.com", cwd=sha256)
        self.git("commit", "--allow-empty", "-m", "initial", cwd=sha256)
        self.repo = sha256
        self.sha = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(len(self.sha), 64)
        result, payload = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["head_sha"], self.sha)

    def test_no_vscode_editor_hooks_or_git_filters(self):
        marker = self.root / "launched"
        fake = self.root / "fake-bin"
        fake.mkdir()
        for name in ("code", "vi", "editor"):
            script = fake / name
            script.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
            script.chmod(0o755)
        hook = self.repo / ".git/hooks/post-checkout"
        hook.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
        hook.chmod(0o755)
        self.git("config", "filter.test.smudge", f'touch "{marker}"; cat')
        self.git("config", "filter.test.clean", f'touch "{marker}"; cat')
        self.git("config", "filter.test.required", "true")
        (self.repo / ".gitattributes").write_text("tracked.txt filter=test\n")
        self.git("add", ".gitattributes")
        self.git("commit", "-m", "filter")
        self.sha = self.git("rev-parse", "HEAD").stdout.strip()
        marker.unlink(missing_ok=True)
        self.env["PATH"] = str(fake) + os.pathsep + self.env["PATH"]
        self.env["EDITOR"] = str(fake / "editor")
        result, _ = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse((self.workspace / ".env.worktree").exists())
        self.assertEqual((self.workspace / "tracked.txt").read_text(), "original\n")
        result, _ = self.remove()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())

    def test_destination_collisions(self):
        self.workspace.parent.mkdir()
        for kind in ("directory", "file", "symlink", "broken_symlink"):
            with self.subTest(kind=kind):
                if kind == "directory":
                    self.workspace.mkdir()
                elif kind == "file":
                    self.workspace.write_text("keep")
                else:
                    self.workspace.symlink_to(self.repo if kind == "symlink" else self.root / "missing")
                payload = self.assert_error(self.create(), "PATH_COLLISION")
                self.assertFalse(payload["created_this_invocation"])
                self.assertIsNone(payload["surviving_path"])
                self.assertTrue(payload["path_exists"])
                if kind == "directory":
                    self.workspace.rmdir()
                else:
                    self.workspace.unlink()

    def test_stale_registration_collision_and_removal(self):
        self.create()
        shutil.rmtree(self.workspace)
        self.assert_error(self.create(), "PATH_COLLISION")
        payload = self.assert_error(self.remove(force=True), "STALE_REGISTRATION")
        self.assertTrue(payload["worktree_registered"])
        self.assertFalse(payload["path_exists"])

    def test_racing_destination_collision_does_not_claim_ownership(self):
        fake = self.root / "fake-bin"
        fake.mkdir()
        mkdir = fake / "mkdir"
        mkdir.write_text(
            '#!/usr/bin/env bash\n'
            f'{shlex.quote(shutil.which("mkdir"))} "$@"\nresult=$?\n'
            'if [[ "$1" == "-p" && $result == 0 ]]; then\n'
            f'  {shlex.quote(shutil.which("mkdir"))} "$MKWT_TEST_COLLISION_PATH"\n'
            '  printf "keep" > "$MKWT_TEST_COLLISION_PATH/other-process"\nfi\nexit "$result"\n'
        )
        mkdir.chmod(0o755)
        self.env["PATH"] = str(fake) + os.pathsep + self.env["PATH"]
        self.env["MKWT_TEST_COLLISION_PATH"] = str(self.workspace)
        payload = self.assert_error(self.create(), "PATH_COLLISION")
        self.assertFalse(payload["created_this_invocation"])
        self.assertIsNone(payload["surviving_path"])
        self.assertEqual((self.workspace / "other-process").read_text(), "keep")

    def test_partial_clone_never_fetches_missing_checkout_objects(self):
        self.git("config", "uploadpack.allowFilter", "true")
        partial = self.root / "partial"
        self.git("clone", "--filter=blob:none", "--no-checkout", self.repo.as_uri(), str(partial), cwd=self.root)
        blob = self.git("rev-parse", "HEAD:tracked.txt").stdout.strip()
        self.assertNotEqual(self.git("--no-lazy-fetch", "cat-file", "-e", blob, cwd=partial, check=False).returncode, 0)
        trace = self.root / "git.trace"
        self.env["GIT_TRACE"] = str(trace)
        self.repo = partial
        self.env_config()
        payload = self.assert_error(self.create(worktree_id="checkout-failed"), "CHECKOUT_FAILED", "partial_failure")
        self.assertEqual(payload["surviving_path"], str(self.workspace))
        self.assertEqual(payload["head_sha"], self.sha)
        self.assertEqual(payload["worktree_id"], "checkout-failed")
        self.assertIsNone(payload["worktree_env_path"])
        self.assert_error(self.create(path=self.root / "retry", worktree_id="checkout-failed"), "DUPLICATE_WORKTREE_ID")
        self.assertNotIn("built-in: git fetch", trace.read_text())
        self.assertNotEqual(self.git("--no-lazy-fetch", "cat-file", "-e", blob, cwd=partial, check=False).returncode, 0)

    def test_removal_refuses_replaced_gitfile(self):
        self.create()
        other = self.root / "other-worktree"
        self.create(path=other)
        (self.workspace / ".git").write_bytes((other / ".git").read_bytes())
        self.assert_error(self.remove(force=True), "NOT_REGISTERED")
        self.assertTrue(self.workspace.exists())
        self.assertTrue(other.exists())

    def test_partial_creation_failure_reports_surviving_worktree(self):
        fake = self.root / "fake-bin"
        fake.mkdir()
        git = fake / "git"
        real_git = shutil.which("git")
        git.write_text(
            '#!/usr/bin/env bash\n'
            f'{shlex.quote(real_git)} "$@"\nresult=$?\n'
            'for arg in "$@"; do\n'
            '  if [[ "$arg" == "add" && " $* " == *" worktree "* && $result == 0 ]]; then\n'
            '    echo "injected failure after registration" >&2\nexit 9\nfi\ndone\nexit "$result"\n'
        )
        git.chmod(0o755)
        self.env["PATH"] = str(fake) + os.pathsep + self.env["PATH"]
        payload = self.assert_error(self.create(), "CREATE_FAILED", "partial_failure")
        self.assertTrue(payload["created_this_invocation"])
        self.assertTrue(payload["worktree_registered"])
        self.assertEqual(payload["surviving_path"], str(self.workspace))
        self.assertEqual(payload["head_sha"], self.sha)
        self.assertTrue((self.workspace / ".git").exists())

    def test_removal_repeated_and_without_config(self):
        self.create()
        other = self.root / "other"
        self.create(path=other)
        self.config.unlink()
        result, payload = self.remove()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["status"], "removed")
        self.assertEqual(payload["head_sha"], self.sha)
        self.assertFalse(payload["worktree_registered"])
        self.assertFalse(payload["path_exists"])
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=other).stdout.strip(), self.sha)
        result, payload = self.remove()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["status"], "already_absent")
        self.assertIsNone(payload["head_sha"])
        self.assertIsNone(payload["detached"])

    def test_remove_using_the_target_as_repository_context(self):
        self.create()
        result, payload = self.remove(repo=self.workspace)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["status"], "removed")
        self.assertFalse(payload["worktree_registered"])
        self.assertFalse(self.workspace.exists())

    def test_dirty_removal_refuses_every_change_kind(self):
        for kind in ("unstaged", "staged", "untracked", "ignored"):
            path = self.root / kind
            self.create(path=path)
            if kind in ("staged", "unstaged"):
                (path / "tracked.txt").write_text("changed\n")
                if kind == "staged":
                    self.git("add", "tracked.txt", cwd=path)
            elif kind == "untracked":
                (path / "new.txt").write_text("new")
            else:
                (path / "ignored").mkdir()
                (path / "ignored/data").write_text("keep")
            self.assert_error(self.remove(path=path), "DIRTY_WORKTREE")
            self.assertTrue(path.exists())
            result, _ = self.remove(path=path, force=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(path.exists())

    def test_removal_preserves_attached_branch(self):
        for force in (False, True):
            path = self.root / f"attached-{force}"
            branch = f"keep-{force}"
            self.git("worktree", "add", "-b", branch, str(path), self.sha)
            if force:
                (path / "tracked.txt").write_text("changed")
            result, payload = self.remove(path=path, force=force)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["branch"], branch)
            self.assertFalse(payload["detached"])
            self.assertEqual(self.git("rev-parse", branch).stdout.strip(), self.sha)

    def test_main_checkout_unregistered_directory_wrong_repo_and_symlink(self):
        self.assert_error(self.remove(path=self.repo, force=True), "MAIN_WORKTREE")
        self.workspace.mkdir(parents=True)
        (self.workspace / "keep").write_text("keep")
        self.assert_error(self.remove(force=True), "NOT_REGISTERED")
        self.assertTrue((self.workspace / "keep").exists())
        shutil.rmtree(self.workspace)
        self.create()
        other = self.root / "other-repo"
        self.git("init", str(other), cwd=self.root)
        self.assert_error(self.remove(repo=other, force=True), "NOT_REGISTERED")
        alias = self.root / "alias"
        alias.symlink_to(self.workspace)
        for path in (alias, str(alias) + "/", str(alias) + "/./"):
            self.assert_error(self.remove(path=path, force=True), "INVALID_PATH")
        self.assertTrue(self.workspace.exists())

    def test_locked_worktree_is_not_force_unlocked(self):
        self.create()
        self.git("worktree", "lock", str(self.workspace))
        self.assert_error(self.remove(force=True), "WORKTREE_LOCKED")
        self.assertTrue(self.workspace.exists())

    def test_json_errors_and_relative_paths(self):
        for args in (
            ("create", "--unknown", "--json"),
            ("remove", "--repo", "--json"),
            ("create", "--repo", self.repo, "--json"),
            ("invalid", "--non-interactive", "--json"),
        ):
            self.assert_error(self.invoke(*args), "INVALID_ARGUMENTS")
        self.assert_error(self.invoke("remove", "--repo", self.root / "missing", "--path", self.workspace,
                                     "--non-interactive", "--json"), "INVALID_REPOSITORY")
        result, payload = self.create(path=Path("relative/../agent"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["workspace_path"], str(self.root / "agent"))

    def test_json_escaping_and_parent_symlink(self):
        parent = self.root / "parent"
        parent.mkdir()
        alias = self.root / "parent alias"
        alias.symlink_to(parent)
        path = alias / 'agent "quote" \\ tab\t newline\n'
        result, payload = self.create(path=path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["workspace_path"], str(parent / path.name))
        result, _ = self.remove(path=path)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ambient_git_repository_does_not_override_repo_option(self):
        self.env["GIT_DIR"] = str(self.root / "nonexistent.git")
        self.env["GIT_WORK_TREE"] = str(self.root / "wrong")
        result, payload = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["head_sha"], self.sha)

    def test_legacy_reserved_branch_names_and_vscode(self):
        config = self.repo / ".worktrees/mkwt.conf"
        config.parent.mkdir()
        config.write_text('BASE_BRANCH="main"\nOPEN_IN_VSCODE="always"\n')
        fake = self.root / "fake-bin"
        fake.mkdir()
        code_log = self.root / "code.log"
        code = fake / "code"
        code.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{code_log}"\n')
        code.chmod(0o755)
        self.env["PATH"] = str(fake) + os.pathsep + self.env["PATH"]
        for branch in ("create", "remove", "feature/day-to-day"):
            result = subprocess.run([str(MKWT), branch], cwd=self.repo, env=self.env,
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            path = self.repo / ".worktrees" / branch
            self.assertEqual(result.stdout, str(path) + "\n")
            self.assertIn(str(path), code_log.read_text())

    def test_installed_executable_has_revision_without_source_checkout(self):
        source = self.root / "source"
        self.git("clone", "--quiet", str(ROOT), str(source), cwd=self.root)
        for path in ("bin/mkwt", "setup.sh"):
            shutil.copy2(ROOT / path, source / path)
        self.git("config", "user.name", "Test", cwd=source)
        self.git("config", "user.email", "test@example.com", cwd=source)
        self.git("add", ".", cwd=source)
        if self.git("diff", "--cached", "--quiet", cwd=source, check=False).returncode:
            self.git("commit", "-m", "test build", cwd=source)
        revision = self.git("rev-parse", "HEAD", cwd=source).stdout.strip()
        install_dir = self.root / "installed"
        env = dict(self.env, MKWT_INSTALL_DIR=str(install_dir))
        result = subprocess.run([str(source / "setup.sh")], env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = install_dir / "mkwt"
        first = installed.read_bytes()
        subprocess.run([str(source / "setup.sh")], env=env, check=True, capture_output=True, timeout=15)
        self.assertEqual(installed.read_bytes(), first)
        shutil.rmtree(source)
        result, payload = self.invoke("--version", "--json", executable=installed)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["source_revision"], revision)
        self.assertEqual(payload["version"], "0.3.0")
        result, _ = self.create(executable=installed)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
