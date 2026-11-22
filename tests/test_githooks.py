"""Hooks in githooks/: Chat-Bestätigung, Identität, S1, kein Hook-Bypass."""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / "githooks"
SCRIPTS = REPO / "scripts"
IDENT_NAME = "Juniormind1"
IDENT_EMAIL = "juniormind@proton.me"


def _git_env(home: Path, **extra: str) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": IDENT_NAME,
        "GIT_AUTHOR_EMAIL": IDENT_EMAIL,
        "GIT_COMMITTER_NAME": IDENT_NAME,
        "GIT_COMMITTER_EMAIL": IDENT_EMAIL,
        "GIT_TERMINAL_PROMPT": "0",
        "GC_AUTO": "0",
        "LC_ALL": "C",
        "LANG": "C",
    }
    for key in (
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "TMP",
        "TEMP",
        "TMPDIR",
    ):
        if key in os.environ:
            env[key] = os.environ[key]
    env.update(extra)
    return env


class _HookRepo:
    def __init__(self, tmp: Path, hooks: Path = HOOKS, branch: str = "dev-juniormind"):
        self.root = tmp / "repo"
        self.home = tmp / "home"
        self.root.mkdir()
        self.home.mkdir()
        self.env = _git_env(self.home)
        self._run(["git", "init", "-b", branch, str(self.root)])
        self._run(["git", "config", "user.name", IDENT_NAME])
        self._run(["git", "config", "user.email", IDENT_EMAIL])
        self._run(["git", "config", "core.hooksPath", str(hooks)])
        self._run(["git", "config", "commit.gpgsign", "false"])
        self._run(["git", "config", "advice.detachedHead", "false"])

    def _run(self, args: list[str], check: bool = True, **kw):
        cwd = kw.pop("cwd", self.root if self.root.exists() else None)
        return subprocess.run(
            args,
            cwd=cwd,
            env=self.env,
            check=check,
            text=True,
            capture_output=True,
            **kw,
        )

    def git(self, *args: str, check: bool = True, env_extra: dict[str, str] | None = None):
        env = self.env if not env_extra else {**self.env, **env_extra}
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            env=env,
            check=check,
            text=True,
            capture_output=True,
        )

    def common_dir(self) -> Path:
        raw = self.git("rev-parse", "--git-common-dir").stdout.strip()
        path = Path(raw)
        if not path.is_absolute():
            path = (self.root / path).resolve()
        return path

    def ok_path(self, kind: str) -> Path:
        return self.common_dir() / f"satsage-{kind}-ok"

    def touch_ok(self, kind: str, age_seconds: float | None = None) -> Path:
        path = self.ok_path(kind)
        path.write_text("ok\n", encoding="utf-8")
        if age_seconds is not None:
            when = time.time() - age_seconds
            os.utime(path, (when, when))
        return path

    def commit(self, message: str, check: bool = True, env_extra: dict[str, str] | None = None):
        return self.git("commit", "-m", message, check=check, env_extra=env_extra)

    def write_and_add(self, rel: str, content: str = "x\n") -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.git("add", "--", rel)

    def combined(self, proc: subprocess.CompletedProcess) -> str:
        return (proc.stdout or "") + (proc.stderr or "")


class TestGithooksCommit(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="satsage-hook-")
        self.addCleanup(self._tmp.cleanup)
        self.repo = _HookRepo(Path(self._tmp.name))

    def test_commit_ohne_ok_datei_ist_rot(self):
        self.repo.write_and_add("README.md", "a\n")
        proc = self.repo.commit("ohne ok", check=False)
        self.assertNotEqual(proc.returncode, 0)
        text = self.repo.combined(proc)
        self.assertIn("Kein Commit ohne explizites OK im Chat", text)
        self.assertIn("satsage-commit-ok", text)
        self.assertIn("erst angelegt", text)
        self.assertFalse(self.repo.git("rev-parse", "--verify", "HEAD", check=False).returncode == 0)

    def test_commit_mit_ok_datei_ist_gruen_und_datei_danach_weg(self):
        self.repo.write_and_add("README.md", "a\n")
        ok = self.repo.touch_ok("commit")
        self.assertTrue(ok.is_file())
        proc = self.repo.commit("mit ok")
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(ok.exists(), "post-commit muss satsage-commit-ok löschen")
        tip = self.repo.git("log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(tip, "mit ok")

    def test_abgelaufene_ok_datei_ist_rot(self):
        self.repo.write_and_add("README.md", "a\n")
        ok = self.repo.touch_ok("commit", age_seconds=3 * 3600)
        proc = self.repo.commit("abgelaufen", check=False)
        self.assertNotEqual(proc.returncode, 0)
        text = self.repo.combined(proc)
        self.assertIn("abgelaufen", text)
        self.assertIn("2 Stunden", text)
        self.assertTrue(ok.is_file(), "abgelaufene Datei bleibt liegen, bis ein neues OK kommt")

    def test_identitaet_bleibt_rot_auch_mit_ok_datei(self):
        self.repo.write_and_add("README.md", "a\n")
        self.repo.touch_ok("commit")
        proc = self.repo.commit(
            "falsche id",
            check=False,
            env_extra={
                "GIT_AUTHOR_NAME": "Falsch",
                "GIT_AUTHOR_EMAIL": "falsch@example.com",
                "GIT_COMMITTER_NAME": "Falsch",
                "GIT_COMMITTER_EMAIL": "falsch@example.com",
            },
        )
        # Config bleibt Juniormind1, aber Author/Committer-Env weicht ab.
        self.assertNotEqual(proc.returncode, 0)
        text = self.repo.combined(proc)
        self.assertIn("SatSage allows only", text)
        self.assertTrue(self.repo.ok_path("commit").is_file(), "OK bleibt bei Identitätsfehler")

    def test_secret_pfad_bleibt_rot_auch_mit_ok_datei(self):
        self.repo.write_and_add("README.md", "a\n")
        self.repo.touch_ok("commit")
        self.repo.commit("basis")
        self.repo.write_and_add(".env", "SECRET=1\n")
        self.repo.touch_ok("commit")
        proc = self.repo.commit("secret", check=False)
        self.assertNotEqual(proc.returncode, 0)
        text = self.repo.combined(proc)
        self.assertIn("secret path", text)
        self.assertIn(".env", text)
        self.assertTrue(self.repo.ok_path("commit").is_file(), "OK bleibt bei S1-Fehler")

    def test_no_verify_loescht_ok_datei_trotzdem(self):
        self.repo.write_and_add("README.md", "a\n")
        self.repo.touch_ok("commit")
        proc = self.repo.git("commit", "--no-verify", "-m", "ohne hook")
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(self.repo.ok_path("commit").exists())

    def test_ok_datei_im_common_dir_gilt_auch_im_worktree(self):
        self.repo.write_and_add("README.md", "a\n")
        self.repo.touch_ok("commit")
        self.repo.commit("basis")
        wt = Path(self._tmp.name) / "worktree"
        self.repo.git("worktree", "add", "-b", "seite", str(wt), "HEAD")
        wt_common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=wt,
            env=self.repo.env,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        wt_common_path = Path(wt_common)
        if not wt_common_path.is_absolute():
            wt_common_path = (wt / wt_common).resolve()
        else:
            wt_common_path = wt_common_path.resolve()
        self.assertEqual(wt_common_path, self.repo.common_dir().resolve())
        (wt / "wt.txt").write_text("w\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "--", "wt.txt"],
            cwd=wt,
            env=self.repo.env,
            check=True,
            text=True,
            capture_output=True,
        )
        proc = subprocess.run(
            ["git", "commit", "-m", "im worktree"],
            cwd=wt,
            env=self.repo.env,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Kein Commit ohne explizites OK im Chat", proc.stderr + proc.stdout)
        ok = self.repo.touch_ok("commit")
        self.assertEqual(ok.resolve(), (self.repo.common_dir() / "satsage-commit-ok").resolve())
        proc = subprocess.run(
            ["git", "commit", "-m", "im worktree"],
            cwd=wt,
            env=self.repo.env,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertFalse(ok.exists())

    def test_pre_merge_commit_braucht_ok(self):
        self.repo.write_and_add("a.txt", "eins\n")
        self.repo.touch_ok("commit")
        self.repo.commit("eins")
        self.repo.git("checkout", "-b", "seite")
        self.repo.write_and_add("b.txt", "zwei\n")
        self.repo.touch_ok("commit")
        self.repo.commit("zwei")
        self.repo.git("checkout", "dev-juniormind")
        self.repo.write_and_add("c.txt", "drei\n")
        self.repo.touch_ok("commit")
        self.repo.commit("drei")
        proc = self.repo.git("merge", "--no-edit", "seite", check=False)
        self.assertNotEqual(proc.returncode, 0, "Merge ohne OK muss scheitern")
        text = self.repo.combined(proc)
        self.assertIn("Kein Commit ohne explizites OK im Chat", text)
        self.assertIn("git commit", text)
        # Git lässt den Merge nach einem Hook-Fehler liegen.
        # Neu ansetzen, damit erneut pre-merge-commit (nicht pre-commit) läuft.
        self.repo.git("merge", "--abort")
        self.repo.touch_ok("commit")
        proc = self.repo.git("merge", "--no-edit", "seite")
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(self.repo.ok_path("commit").exists())
        parents = self.repo.git("rev-list", "--parents", "-n", "1", "HEAD").stdout.split()
        self.assertGreaterEqual(len(parents), 3, "Merge-Commit mit zwei Eltern erwartet")


class TestGithooksPush(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="satsage-hook-push-")
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.repo = _HookRepo(base)
        self.bare = base / "Juniormind1" / "SatSage.git"
        self.bare.parent.mkdir(parents=True)
        env = self.repo.env
        subprocess.run(
            ["git", "init", "--bare", str(self.bare)],
            check=True,
            env=env,
            text=True,
            capture_output=True,
        )
        self.repo.git("remote", "add", "origin", str(self.bare))
        self.repo.write_and_add("README.md", "a\n")
        self.repo.touch_ok("commit")
        self.repo.commit("basis")

    def test_push_ohne_ok_datei_ist_rot(self):
        proc = self.repo.git("push", "-u", "origin", "HEAD:refs/heads/dev-juniormind", check=False)
        self.assertNotEqual(proc.returncode, 0)
        text = self.repo.combined(proc)
        self.assertIn("Kein Push ohne explizites OK im Chat", text)
        self.assertIn("satsage-push-ok", text)
        # Remote bleibt leer
        heads = subprocess.run(
            ["git", "ls-remote", "--heads", str(self.bare)],
            env=self.repo.env,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(heads.strip(), "")

    def test_push_mit_ok_datei_ist_gruen_und_datei_danach_weg(self):
        ok = self.repo.touch_ok("push")
        proc = self.repo.git("push", "-u", "origin", "HEAD:refs/heads/dev-juniormind")
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(ok.exists(), "pre-push muss satsage-push-ok vor exit 0 löschen")
        heads = subprocess.run(
            ["git", "ls-remote", "--heads", str(self.bare)],
            env=self.repo.env,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        self.assertIn("refs/heads/dev-juniormind", heads)

    def test_push_nach_main_ohne_ok_scheitert_vor_der_suite(self):
        """Ohne OK darf nicht erst das fehlende .venv die Meldung liefern."""
        proc = self.repo.git("push", "origin", "HEAD:refs/heads/main", check=False)
        self.assertNotEqual(proc.returncode, 0)
        text = self.repo.combined(proc)
        self.assertIn("Kein Push ohne explizites OK im Chat", text)
        self.assertNotIn(".venv", text)
        self.assertNotIn("Unit-Suite", text)

    def test_push_nur_branch_loeschung_braucht_ok(self):
        self.repo.touch_ok("push")
        self.repo.git("push", "origin", "HEAD:refs/heads/dev-juniormind")
        self.repo.touch_ok("push")
        self.repo.git("push", "origin", "HEAD:refs/heads/wegdamit")
        proc = self.repo.git("push", "origin", ":refs/heads/wegdamit", check=False)
        self.assertNotEqual(proc.returncode, 0)
        text = self.repo.combined(proc)
        self.assertIn("Kein Push ohne explizites OK im Chat", text)
        heads = subprocess.run(
            ["git", "ls-remote", "--heads", str(self.bare)],
            env=self.repo.env,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        self.assertIn("refs/heads/wegdamit", heads)
        self.repo.touch_ok("push")
        proc = self.repo.git("push", "origin", ":refs/heads/wegdamit")
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(self.repo.ok_path("push").exists())
        heads = subprocess.run(
            ["git", "ls-remote", "--heads", str(self.bare)],
            env=self.repo.env,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        self.assertNotIn("refs/heads/wegdamit", heads)

    def test_push_an_anderes_remote_ohne_ok_ist_erlaubt(self):
        other = Path(self._tmp.name) / "other.git"
        subprocess.run(
            ["git", "init", "--bare", str(other)],
            check=True,
            env=self.repo.env,
            text=True,
            capture_output=True,
        )
        self.repo.git("remote", "add", "other", str(other))
        proc = self.repo.git("push", "other", "HEAD:refs/heads/dev-juniormind")
        self.assertEqual(proc.returncode, 0)

    def test_abgelaufene_push_ok_datei_ist_rot(self):
        self.repo.touch_ok("push", age_seconds=3 * 3600)
        proc = self.repo.git("push", "origin", "HEAD:refs/heads/dev-juniormind", check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("abgelaufen", self.repo.combined(proc))
        self.assertTrue(self.repo.ok_path("push").is_file())


class TestGithooksMeta(unittest.TestCase):
    def test_hook_dateien_sind_ausfuehrbar_und_haben_lf(self):
        for name in ("pre-commit", "pre-push", "post-commit", "pre-merge-commit"):
            path = HOOKS / name
            self.assertTrue(path.is_file(), name)
            data = path.read_bytes()
            self.assertFalse(data.startswith(b"\xef\xbb\xbf"), name)
            self.assertNotIn(b"\r", data, f"{name} muss LF haben")
            mode = path.stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, f"{name} muss ausführbar sein")

    def test_pre_merge_commit_ruft_pre_commit_auf(self):
        text = (HOOKS / "pre-merge-commit").read_text(encoding="utf-8")
        self.assertIn('"$HOOKDIR/pre-commit"', text)
        self.assertIn("satsage-commit-ok", text)
        # Kein exec: nach pre-commit muss die OK-Datei gelöscht werden,
        # weil git merge post-commit nicht aufruft.
        self.assertIn("rm -f", text)

    def test_maintainer_skripte_umgehen_die_hooks_nicht(self):
        for name in ("commit.sh", "commit.bat", "push.sh", "push.bat"):
            path = SCRIPTS / name
            raw = path.read_bytes()
            # .bat ist CRLF, Prüfung trotzdem auf --no-verify
            text = raw.decode("utf-8")
            self.assertNotIn("--no-verify", text, f"{name} darf die Hooks nicht umgehen")
            self.assertNotIn("satsage-commit-ok", text)
            self.assertNotIn("satsage-push-ok", text)


if __name__ == "__main__":
    unittest.main()
