from pathlib import Path
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAFE_DIRECTORY = f"safe.directory={PROJECT_ROOT.resolve().as_posix()}"


@pytest.mark.parametrize(
    "relative_path",
    [
        "config/settings.json",
        "config/secrets.enc",
        "config/.secret_key",
        "config/secrets.dpapi",
        "config/secrets.dpapi.tmp",
        "config/secrets.dpapi.backup",
        "config/secrets.dpapi~",
        "config/.secrets.dpapi.atomic.tmp",
    ],
)
def test_sensitive_runtime_files_are_git_ignored(
    relative_path: str,
) -> None:
    result = subprocess.run(
        [
            "git",
            "-c",
            SAFE_DIRECTORY,
            "check-ignore",
            "--no-index",
            "--quiet",
            relative_path,
        ],
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_dpapi_ignore_rule_does_not_hide_default_settings() -> None:
    result = subprocess.run(
        [
            "git",
            "-c",
            SAFE_DIRECTORY,
            "check-ignore",
            "--no-index",
            "--quiet",
            "config/default_settings.json",
        ],
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert result.returncode == 1
