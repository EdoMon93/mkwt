import json
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

    def create(self, path=None, sha=None, **kwargs):
        return self.invoke(
            "create", "--repo", self.repo, "--path", path or self.workspace,
            "--commit", sha or self.sha, "--detach", "--config", self.config,
            "--non-interactive", "--json", **kwargs,
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
                        'WORKTREE_ENV="KEY=value"\n', 'UNKNOWN=""\n', "BASE_BRANCH='unterminated\n",
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
        payload = self.assert_error(self.create(), "CHECKOUT_FAILED", "partial_failure")
        self.assertEqual(payload["surviving_path"], str(self.workspace))
        self.assertEqual(payload["head_sha"], self.sha)
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
        self.assertTrue(payload["version"].startswith("0.2.0"))
        result, _ = self.create(executable=installed)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
