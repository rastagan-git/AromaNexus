import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from aromanexus import __version__
from aromanexus.cli import main
from aromanexus.models import LookupResult
from aromanexus.sources.nist import NistWebBookClient
from flavor_data_crawler.cli import main as legacy_main
from flavor_data_crawler.models import LookupResult as LegacyLookupResult
from flavor_data_crawler.sources.nist import NistWebBookClient as LegacyNistWebBookClient

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_primary_and_legacy_import_namespaces_share_public_types():
    assert LegacyLookupResult is LookupResult
    assert LegacyNistWebBookClient is NistWebBookClient
    assert legacy_main is main


def test_aromanexus_is_primary_distribution_and_cli_with_legacy_alias():
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["name"] == "aromanexus"
    assert config["project"]["version"] == __version__
    scripts = config["project"]["scripts"]
    assert scripts["aromanexus"] == "aromanexus.cli:main"
    assert scripts["flavor-data"] == "aromanexus.cli:main"
    assert config["project"]["urls"]["Repository"].endswith("/rastagan-git/AromaNexus")


def test_readmes_use_current_brand_and_preserve_language_links():
    english = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (REPO_ROOT / "README-CN.md").read_text(encoding="utf-8")
    assert english.startswith("# AromaNexus\n")
    assert chinese.startswith("# AromaNexus\n")
    assert "[简体中文](README-CN.md)" in english
    assert "[English](README.md)" in chinese


def test_legacy_module_cli_forwards_to_aromanexus():
    completed = subprocess.run(
        [sys.executable, "-m", "flavor_data_crawler.cli", "--version"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == f"aromanexus {__version__}"


@pytest.mark.parametrize("argument", ["--version", "--help"])
def test_primary_module_cli_matches_console_module(argument):
    package_entry = subprocess.run(
        [sys.executable, "-m", "aromanexus", argument],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    console_module = subprocess.run(
        [sys.executable, "-m", "aromanexus.cli", argument],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert package_entry.returncode == console_module.returncode == 0
    assert package_entry.stdout == console_module.stdout
    assert package_entry.stderr == console_module.stderr


def test_primary_module_cli_preserves_argparse_error_exit_code():
    completed = subprocess.run(
        [sys.executable, "-m", "aromanexus"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "command" in completed.stderr
