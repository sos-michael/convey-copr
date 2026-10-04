"""Exercise scheduling across fresh runners without network requests."""
import base64
import contextlib
import io
import os
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zlib

import weekly

COMMIT = "a" * 40
TARGETS = ["fedora-44-x86_64", "fedora-rawhide-x86_64"]


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.build_proxy.get_list.return_value = []
        self.client.build_proxy.create_from_custom.return_value = SimpleNamespace(id=123)
        self.client.project_proxy.get.return_value = {"chroot_repos": dict.fromkeys(TARGETS)}
        self.client.build_proxy.get_source_build_config.return_value = {
            "source_dict": {"script": weekly.render(COMMIT)}}

    def latest(self, state="succeeded", targets=TARGETS):
        self.client.build_proxy.get_list.return_value = [
            {"id": 123, "state": state, "chroots": targets}]

    def run_scheduler(self, *options, commit=COMMIT):
        with patch("sys.argv", ["weekly.py", "--commit", commit, *options]), \
             patch("copr.v3.Client.create_from_config_file", return_value=self.client), \
             contextlib.redirect_stdout(io.StringIO()):
            weekly.main()

    def test_successful_build_is_not_duplicated_on_fresh_runner(self):
        self.latest()
        self.run_scheduler()
        self.client.build_proxy.create_from_custom.assert_not_called()
        self.run_scheduler(commit="b" * 40)
        self.client.build_proxy.create_from_custom.assert_called_once()

    def test_active_build_is_not_duplicated_even_when_forced(self):
        for state in ("pending", "starting", "importing", "running"):
            with self.subTest(state=state):
                self.latest(state)
                self.run_scheduler("--force")
        self.client.build_proxy.create_from_custom.assert_not_called()
        self.client.build_proxy.get_source_build_config.assert_not_called()

    def test_failed_builds_retry(self):
        for state in ("failed", "canceled", "skipped"):
            with self.subTest(state=state):
                self.latest(state)
                self.assertTrue(weekly.check(self.client, weekly.render(COMMIT))[0])

    def test_first_build_is_submitted(self):
        self.run_scheduler()
        self.client.build_proxy.create_from_custom.assert_called_once()

    def test_packaging_change_rebuilds_same_commit(self):
        self.latest()
        with patch("weekly.render", return_value=weekly.render(COMMIT) + "\n# changed\n"):
            self.run_scheduler()
        self.client.build_proxy.create_from_custom.assert_called_once()

    def test_missing_target_requires_build(self):
        self.latest(targets=TARGETS[:1])
        self.run_scheduler()
        self.client.build_proxy.create_from_custom.assert_called_once()

    def test_force_rebuilds_successful_unchanged_recipe(self):
        self.latest()
        self.run_scheduler("--force")
        self.client.build_proxy.create_from_custom.assert_called_once()

    def test_dry_run_neither_submits_nor_waits(self):
        with patch("weekly.watch") as watch:
            self.run_scheduler("--dry-run", "--force", "--wait")
        self.client.build_proxy.create_from_custom.assert_not_called()
        watch.assert_not_called()

    def test_submission_failure_propagates(self):
        self.client.build_proxy.create_from_custom.side_effect = RuntimeError("offline")
        with self.assertRaises(RuntimeError):
            self.run_scheduler()

    def test_copr_failure_fails_workflow(self):
        with patch("weekly.watch", side_effect=subprocess.CalledProcessError(1, "copr-cli")):
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_scheduler("--wait")

    def test_waits_for_existing_build_then_checks_again(self):
        self.latest("running")
        with patch("weekly.watch", side_effect=lambda _: self.latest()) as watch:
            self.run_scheduler("--wait")
        watch.assert_called_once_with(123)
        self.client.build_proxy.create_from_custom.assert_not_called()

    def test_wait_uses_explicit_config_and_checks_exit_status(self):
        with patch.dict(os.environ, {"COPR_CONFIG_FILE": "/tmp/test-copr-config"}), \
             patch("weekly.subprocess.run") as run:
            weekly.watch(123)
        args = run.call_args.args[0]
        self.assertEqual(args[1:], ["--config", "/tmp/test-copr-config", "watch-build", "123"])
        self.assertTrue(run.call_args.kwargs["check"])

    def test_compression_variations_do_not_trigger_build(self):
        template = (weekly.ROOT / "source.py.in").read_text()
        spec = (weekly.ROOT / "convey.spec.in").read_bytes()
        alternate = template.replace("@PIN@", repr(COMMIT)).replace(
            "@SPEC@", repr(base64.b64encode(zlib.compress(spec, 1)).decode()))
        self.assertEqual(weekly.fingerprint(alternate), weekly.fingerprint(weekly.render(COMMIT)))

    def test_script_fits_copr_limit_and_compiles(self):
        script = weekly.render(COMMIT)
        self.assertLessEqual(len(script.encode()), 4000)
        compile(script, "source.generated.py", "exec")


if __name__ == "__main__":
    unittest.main()
