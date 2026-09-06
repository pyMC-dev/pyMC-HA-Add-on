from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDONS = ("openhop_repeater_dev", "openhop_repeater_main")


def wait_for_file(path: Path, process: subprocess.Popen[str], timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            raise AssertionError(
                f"wrapper exited early with {process.returncode}:\n{process.stdout.read() if process.stdout else ''}"
            )
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {path}")


def make_runtime(root: Path, main_source: str) -> Path:
    package_root = root / "pythonpath"
    repeater = package_root / "repeater"
    repeater.mkdir(parents=True)
    (repeater / "__init__.py").write_text("__version__ = 'test'\n", encoding="utf-8")
    (repeater / "main.py").write_text(textwrap.dedent(main_source).lstrip(), encoding="utf-8")
    return package_root


def base_env(root: Path, addon: str, package_root: Path) -> dict[str, str]:
    helper = ROOT / addon / "rootfs/usr/local/lib/openhop-addon/config_bootstrap.py"
    template = root / "template.yaml"
    template.write_text(
        "repeater:\n"
        "  node_name: lifecycle-test\n"
        "  security:\n"
        "    admin_password: admin123\n"
        "    guest_password: guest123\n"
        '    jwt_secret: ""\n'
        "radio_type: null\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(package_root),
            "OPENHOP_ADDON_CONFIG_DIR": str(root / "config"),
            "OPENHOP_ADDON_DATA_DIR": str(root / "data"),
            "OPENHOP_ADDON_RUNTIME_CONFIG_DIR": str(root / "etc/openhop_repeater"),
            "OPENHOP_ADDON_TEMPLATE_CONFIG": str(template),
            "OPENHOP_ADDON_CONFIG_HELPER": str(helper),
            "OPENHOP_ADDON_PYTHON": sys.executable,
            "OPENHOP_ADDON_STABLE_SECONDS": "30",
            "OPENHOP_ADDON_RESTART_DELAY": "0",
            "OPENHOP_TEST_ROOT": str(root),
        }
    )
    return env


class RuntimeLifecycleTests(unittest.TestCase):
    def test_channel_wrappers_are_identical(self) -> None:
        scripts = [ROOT / addon / "run.sh" for addon in ADDONS]
        self.assertEqual(scripts[0].read_bytes(), scripts[1].read_bytes())

    def test_user_site_packages_are_visible_before_bootstrap(self) -> None:
        text = (ROOT / ADDONS[0] / "run.sh").read_text(encoding="utf-8")
        self.assertLess(
            text.index("export PYTHONPATH"),
            text.index('"${PYTHON}" "${CONFIG_HELPER}" bootstrap'),
        )

    def test_packaged_supervisor_is_selected_and_restarted(self) -> None:
        source = """
            import os
            from pathlib import Path

            root = Path(os.environ["OPENHOP_TEST_ROOT"])
            count_path = root / "supervisor.starts"
            count = int(count_path.read_text()) + 1 if count_path.exists() else 1
            count_path.write_text(str(count))
        """
        for addon in ADDONS:
            with self.subTest(addon=addon), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                package_root = make_runtime(root, "raise SystemExit(42)")
                plugins = package_root / "repeater/plugins"
                plugins.mkdir()
                (plugins / "__init__.py").write_text("")
                (plugins / "container_supervisor.py").write_text(textwrap.dedent(source))
                env = base_env(root, addon, package_root)
                env["OPENHOP_ADDON_MAX_RAPID_RESTARTS"] = "2"
                result = subprocess.run(
                    ["sh", str(ROOT / addon / "run.sh")], env=env,
                    capture_output=True, text=True, timeout=15, check=False,
                )
                self.assertTrue((root / "supervisor.starts").exists(), result.stdout + result.stderr)
                self.assertEqual((root / "supervisor.starts").read_text(), "3")
                self.assertIn("rapid restart limit", result.stderr)

    def test_broken_supervisor_does_not_fall_back_to_repeater(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = make_runtime(root, "raise RuntimeError('fallback must not run')")
            plugins = package_root / "repeater/plugins"
            plugins.mkdir()
            (plugins / "__init__.py").write_text("")
            (plugins / "container_supervisor.py").write_text("raise SystemExit(23)\n")
            result = subprocess.run(
                ["sh", str(ROOT / ADDONS[0] / "run.sh")],
                env=base_env(root, ADDONS[0], package_root),
                capture_output=True, text=True, timeout=15, check=False,
            )
            self.assertIn("status 23", result.stderr)
            self.assertNotIn("fallback must not run", result.stderr)

    def test_sigterm_is_forwarded_and_child_is_reaped(self) -> None:
        child_source = """
            import os
            import pathlib
            import signal
            import time

            root = pathlib.Path(os.environ["OPENHOP_TEST_ROOT"])
            root.joinpath("child.pid").write_text(str(os.getpid()), encoding="utf-8")

            def stop(signum, frame):
                root.joinpath("child.stopped").write_text(str(signum), encoding="utf-8")
                raise SystemExit(0)

            signal.signal(signal.SIGTERM, stop)
            while True:
                time.sleep(1)
        """
        for addon in ADDONS:
            with self.subTest(addon=addon), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                package_root = make_runtime(root, child_source)
                process = subprocess.Popen(
                    ["sh", str(ROOT / addon / "run.sh")],
                    env=base_env(root, addon, package_root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                try:
                    wait_for_file(root / "child.pid", process)
                    child_pid = int((root / "child.pid").read_text(encoding="utf-8"))
                    stop_started = time.monotonic()
                    process.send_signal(signal.SIGTERM)
                    output, _ = process.communicate(timeout=15)
                    stop_elapsed = time.monotonic() - stop_started
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)

                self.assertEqual(process.returncode, 0, output)
                self.assertLess(stop_elapsed, 3, output)
                self.assertTrue((root / "child.stopped").is_file(), output)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)

    def test_unresponsive_child_is_killed_before_supervisor_timeout(self) -> None:
        child_source = """
            import os
            import pathlib
            import signal
            import time

            root = pathlib.Path(os.environ["OPENHOP_TEST_ROOT"])
            root.joinpath("child.pid").write_text(str(os.getpid()), encoding="utf-8")
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            while True:
                time.sleep(1)
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = make_runtime(root, child_source)
            process = subprocess.Popen(
                ["sh", str(ROOT / ADDONS[0] / "run.sh")],
                env=base_env(root, ADDONS[0], package_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            child_pid = 0
            try:
                wait_for_file(root / "child.pid", process)
                child_pid = int((root / "child.pid").read_text(encoding="utf-8"))
                process.send_signal(signal.SIGTERM)
                output, _ = process.communicate(timeout=9.5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                if child_pid:
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

            self.assertEqual(process.returncode, 0, output)
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)

    def test_rapid_clean_exit_loop_is_bounded(self) -> None:
        child_source = """
            import os
            import pathlib

            root = pathlib.Path(os.environ["OPENHOP_TEST_ROOT"])
            count_path = root / "starts"
            count = int(count_path.read_text()) + 1 if count_path.exists() else 1
            count_path.write_text(str(count), encoding="utf-8")
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = make_runtime(root, child_source)
            env = base_env(root, ADDONS[0], package_root)
            env["OPENHOP_ADDON_MAX_RAPID_RESTARTS"] = "2"

            result = subprocess.run(
                ["sh", str(ROOT / ADDONS[0] / "run.sh")],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((root / "starts").read_text(encoding="utf-8"), "3")
            self.assertIn("rapid restart limit", result.stderr + result.stdout)

    def test_sigterm_during_restart_delay_does_not_start_another_child(self) -> None:
        child_source = """
            import os
            import pathlib
            import time

            root = pathlib.Path(os.environ["OPENHOP_TEST_ROOT"])
            count_path = root / "starts"
            count = int(count_path.read_text()) + 1 if count_path.exists() else 1
            count_path.write_text(str(count), encoding="utf-8")
            if count > 1:
                root.joinpath("child.pid").write_text(str(os.getpid()), encoding="utf-8")
                while True:
                    time.sleep(1)
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = make_runtime(root, child_source)
            env = base_env(root, ADDONS[0], package_root)
            env["OPENHOP_ADDON_RESTART_DELAY"] = "3"
            process = subprocess.Popen(
                ["sh", str(ROOT / ADDONS[0] / "run.sh")],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            child_pid = 0
            try:
                wait_for_file(root / "starts", process)
                time.sleep(0.2)
                process.send_signal(signal.SIGTERM)
                output, _ = process.communicate(timeout=4)
                if (root / "child.pid").exists():
                    child_pid = int((root / "child.pid").read_text(encoding="utf-8"))
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                if (root / "child.pid").exists():
                    child_pid = int((root / "child.pid").read_text(encoding="utf-8"))
                if child_pid:
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

            self.assertEqual(process.returncode, 0, output)
            self.assertEqual((root / "starts").read_text(encoding="utf-8"), "1")


if __name__ == "__main__":
    unittest.main()
