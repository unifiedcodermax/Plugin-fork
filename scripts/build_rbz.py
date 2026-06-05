#!/usr/bin/env python3
"""Build script for packaging Planara as a .rbz SketchUp extension.

Usage (from the repo root):
    python scripts/build_rbz.py          # build for the current platform
    python scripts/build_rbz.py --skip-engine  # skip PyInstaller, reuse existing dist/

The script:
  1. Compiles planara_engine into a standalone binary via PyInstaller.
  2. Stages the Ruby plugin files + the compiled engine into a temp dir.
  3. Zips the staging directory into  dist/Planara-<version>-<platform>.rbz

Requirements:
  - Python 3.11+
  - PyInstaller  (pip install pyinstaller)
  - The planara_engine virtualenv activated (or the package installed)
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (relative to this script, which lives in scripts/)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = REPO_ROOT / "planara_engine"
PLUGIN_DIR = REPO_ROOT / "planara_plugin"
DIST_DIR = REPO_ROOT / "dist"
SPEC_FILE = ENGINE_DIR / "planara_engine.spec"

# Read version from the engine's __init__.py
VERSION_FILE = ENGINE_DIR / "src" / "planara_engine" / "__init__.py"


def get_version() -> str:
    """Extract __version__ from planara_engine/__init__.py."""
    text = VERSION_FILE.read_text()
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=")[1].strip().strip('"').strip("'")
    return "0.0.0"


def get_platform_tag() -> str:
    """Return a short platform identifier: 'macos' or 'windows'."""
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    return system  # linux, etc.


def build_engine() -> Path:
    """Run PyInstaller and return the path to the output folder."""
    print("=" * 60)
    print("  Step 1: Building planara-engine with PyInstaller")
    print("=" * 60)

    if not SPEC_FILE.exists():
        sys.exit(f"ERROR: spec file not found at {SPEC_FILE}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        str(SPEC_FILE),
    ]

    print(f"  Running: {' '.join(cmd)}")
    print(f"  Working dir: {ENGINE_DIR}")
    subprocess.check_call(cmd, cwd=str(ENGINE_DIR))

    engine_dist = ENGINE_DIR / "dist" / "planara-engine"
    if not engine_dist.is_dir():
        sys.exit(f"ERROR: PyInstaller output not found at {engine_dist}")

    print(f"  [OK] Engine compiled -> {engine_dist}")
    return engine_dist


def stage_rbz(engine_dist: Path, platform_tag: str) -> Path:
    """Assemble the .rbz directory layout in a temp staging area."""
    print()
    print("=" * 60)
    print("  Step 2: Staging .rbz contents")
    print("=" * 60)

    staging = DIST_DIR / "staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    # -- 1. Copy loader.rb (the extension registrar) -------------------------
    src_loader = PLUGIN_DIR / "loader.rb"
    if not src_loader.exists():
        sys.exit(f"ERROR: loader.rb not found at {src_loader}")
    shutil.copy2(src_loader, staging / "loader.rb")
    print(f"  [OK] Copied loader.rb")

    # -- 2. Copy the planara/ subfolder (Ruby plugin code) -------------------
    src_planara = PLUGIN_DIR / "planara"
    dst_planara = staging / "planara"
    shutil.copytree(
        src_planara,
        dst_planara,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )
    print(f"  [OK] Copied planara/ plugin code")

    # -- 3. Copy the compiled engine binary into planara/bin/<platform>/ ------
    bin_dir = dst_planara / "bin" / platform_tag / "planara-engine"
    shutil.copytree(
        engine_dist,
        bin_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    print(f"  [OK] Copied engine binary -> planara/bin/{platform_tag}/planara-engine/")

    return staging


def create_rbz(staging: Path, version: str, platform_tag: str) -> Path:
    """Zip the staging directory into a .rbz file."""
    print()
    print("=" * 60)
    print("  Step 3: Creating .rbz archive")
    print("=" * 60)

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    rbz_name = f"Planara-{version}-{platform_tag}.rbz"
    rbz_path = DIST_DIR / rbz_name

    if rbz_path.exists():
        rbz_path.unlink()

    with zipfile.ZipFile(rbz_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(staging.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(staging)
                zf.write(file_path, arcname)

    size_mb = rbz_path.stat().st_size / (1024 * 1024)
    print(f"  [OK] Created {rbz_path.name}  ({size_mb:.1f} MB)")
    print(f"    Path: {rbz_path}")

    return rbz_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Planara .rbz SketchUp extension package.",
    )
    parser.add_argument(
        "--skip-engine",
        action="store_true",
        help="Skip the PyInstaller build step (reuse existing dist/).",
    )
    args = parser.parse_args()

    version = get_version()
    platform_tag = get_platform_tag()

    print(f"Planara build  v{version}  platform={platform_tag}")
    print()

    # Step 1: Compile engine
    if args.skip_engine:
        engine_dist = ENGINE_DIR / "dist" / "planara-engine"
        if not engine_dist.is_dir():
            sys.exit(
                f"ERROR: --skip-engine was passed but {engine_dist} does not exist.\n"
                "Run without --skip-engine first."
            )
        print("  Skipping engine build (--skip-engine)")
    else:
        engine_dist = build_engine()

    # Step 2: Stage files
    staging = stage_rbz(engine_dist, platform_tag)

    # Step 3: Zip into .rbz
    rbz_path = create_rbz(staging, version, platform_tag)

    # Cleanup staging
    shutil.rmtree(staging, ignore_errors=True)

    print()
    print("=" * 60)
    print("  BUILD COMPLETE")
    print("=" * 60)
    print()
    print(f"  Install in SketchUp:")
    print(f"    Window -> Extension Manager -> Install Extension")
    print(f"    Select: {rbz_path}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
