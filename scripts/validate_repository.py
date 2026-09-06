#!/usr/bin/env python3
"""Validate the two-channel Home Assistant add-on repository."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = {
    "openhop_repeater_dev": {
        "channel": "dev",
        "image": "openhop/openhop-repeater:dev",
    },
    "openhop_repeater_main": {
        "channel": "main",
        "image": "openhop/openhop-repeater:main",
    },
}
REQUIRED_FILES = {
    "CHANGELOG.md",
    "DOCS.md",
    "Dockerfile",
    "README.md",
    "config.yaml",
    "icon.png",
    "logo.png",
    "openhop-repeater.example.yaml",
    "run.sh",
    "translations/en.yaml",
}
HELPER = Path("rootfs/usr/local/lib/openhop-addon/config_bootstrap.py")


def fail(message: str) -> None:
    raise AssertionError(message)


def load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        fail(f"{path.relative_to(ROOT)} is invalid YAML: {exc}")


def validate_repository_metadata() -> None:
    metadata = load_yaml(ROOT / "repository.yaml")
    if not isinstance(metadata, dict):
        fail("repository.yaml must contain a mapping")
    for key in ("name", "url", "maintainer"):
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            fail(f"repository.yaml is missing {key}")


def validate_addon(name: str, expected: dict[str, str]) -> None:
    addon = ROOT / name
    missing = sorted(path for path in REQUIRED_FILES if not (addon / path).exists())
    if missing:
        fail(f"{name} is missing required files: {', '.join(missing)}")

    config = load_yaml(addon / "config.yaml")
    if not isinstance(config, dict):
        fail(f"{name}/config.yaml must contain a mapping")
    if config.get("slug") != name:
        fail(f"{name} slug does not match its directory")
    if config.get("backup") != "cold":
        fail(f"{name} must use cold backups")
    if config.get("host_network") is not True:
        fail(f"{name} must retain host networking")
    if config.get("full_access") is not True or config.get("apparmor") is not False:
        fail(f"{name} must retain its hardware access model")
    if config.get("init") is not True:
        fail(f"{name} must retain Home Assistant init")
    expected_mounts = [
        {"type": "addon_config", "path": "/config", "read_only": False},
        {"type": "data", "path": "/var/lib/openhop_repeater", "read_only": False},
    ]
    if config.get("map") != expected_mounts:
        fail(f"{name} has unexpected persistent mounts")
    if not {"aarch64", "amd64"}.issubset(set(config.get("arch", []))):
        fail(f"{name} must support aarch64 and amd64")

    example = load_yaml(addon / "openhop-repeater.example.yaml")
    if not isinstance(example, dict) or "repeater" not in example or "radio_type" not in example:
        fail(f"{name} example configuration is incomplete")

    helper = addon / HELPER
    if not helper.is_file():
        fail(f"{name} is missing {HELPER}")

    dockerfile = (addon / "Dockerfile").read_text(encoding="utf-8")
    required_docker_fragments = (
        f"FROM {expected['image']}",
        "COPY rootfs /",
        "cp /opt/openhop_repeater/config.yaml.example",
        "STOPSIGNAL SIGTERM",
    )
    for fragment in required_docker_fragments:
        if fragment not in dockerfile:
            fail(f"{name}/Dockerfile is missing {fragment!r}")
    if "git+" in dockerfile or "pip install" in dockerfile:
        fail(f"{name}/Dockerfile must use the prebuilt upstream runtime")

    run_script = (addon / "run.sh").read_text(encoding="utf-8")
    for fragment in (
        "config_bootstrap.py",
        "OPENHOP_ADDON_MAX_RAPID_RESTARTS",
        "forward_stop",
        "rapid restart limit",
        '"${PYTHON}" -m "${RUNTIME_MODULE}"',
        "repeater.plugins.container_supervisor",
        'else "repeater.main"',
    ):
        if fragment not in run_script:
            fail(f"{name}/run.sh is missing {fragment!r}")
    if "/data/venv" in run_script or "git+" in run_script or ".update_channel" in run_script:
        fail(f"{name}/run.sh must not install or switch branches")

    state_path = ROOT / ".github" / f"upstream-{expected['channel']}.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("addon_dir") != name or state.get("image") != expected["image"]:
        fail(f"{state_path.relative_to(ROOT)} does not match {name}")


def validate_channel_parity() -> None:
    dev = ROOT / "openhop_repeater_dev"
    main = ROOT / "openhop_repeater_main"
    for relative in (Path("run.sh"), HELPER):
        if (dev / relative).read_bytes() != (main / relative).read_bytes():
            fail(f"shared channel file differs: {relative}")


def main() -> int:
    validate_repository_metadata()
    for name, expected in CHANNELS.items():
        validate_addon(name, expected)
    validate_channel_parity()
    print("Validated 2 add-ons: openhop_repeater_dev, openhop_repeater_main")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, json.JSONDecodeError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
