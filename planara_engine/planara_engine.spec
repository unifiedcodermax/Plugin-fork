# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for bundling planara-engine into a standalone executable.

Build with:
    cd planara_engine
    pyinstaller planara_engine.spec

The output lands in dist/planara-engine/ (a single-folder distribution).
"""

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SPEC_DIR = SPECPATH  # PyInstaller sets SPECPATH to the directory of the spec file
SRC_DIR = os.path.join(SPEC_DIR, "src")
ENGINE_PKG = os.path.join(SRC_DIR, "planara_engine")

# ---------------------------------------------------------------------------
# Data files — rule packs shipped with the engine
# ---------------------------------------------------------------------------
packs_dir = os.path.join(ENGINE_PKG, "rules", "packs")
datas = [(packs_dir, os.path.join("planara_engine", "rules", "packs"))]

# ---------------------------------------------------------------------------
# Hidden imports
#
# PyInstaller's static analysis misses several imports:
#   - uvicorn uses importlib to load its workers and protocol modules
#   - FastAPI / Starlette load encoders and template engines lazily
#   - planara_engine.api.app is imported by string in uvicorn.run()
#   - planara_engine.compliance is a side-effect import that registers
#     evaluators; its submodules must be reachable
#   - bcrypt._bcrypt is a native extension loaded at runtime
#   - email.mime.* pulled in by httpx / multipart
# ---------------------------------------------------------------------------
hidden_imports = [
    # --- The engine's own packages (uvicorn loads api.app by string) ---
    "planara_engine",
    "planara_engine.cli",
    "planara_engine.api",
    "planara_engine.api.app",
    "planara_engine.api.errors",
    "planara_engine.api.middleware",
    "planara_engine.api.routes_auth",
    "planara_engine.api.routes_health",
    "planara_engine.api.routes_history",
    "planara_engine.api.routes_projects",
    "planara_engine.api.routes_reports",
    "planara_engine.api.routes_validate",
    "planara_engine.auth",
    "planara_engine.auth.deps",
    "planara_engine.auth.passwords",
    "planara_engine.auth.service",
    "planara_engine.auth.tokens",
    "planara_engine.compliance",
    "planara_engine.compliance.coverage",
    "planara_engine.compliance.fsi",
    "planara_engine.compliance.height",
    "planara_engine.compliance.parking",
    "planara_engine.compliance.setback",
    "planara_engine.compliance.params",
    "planara_engine.core",
    "planara_engine.core.errors",
    "planara_engine.core.logging",
    "planara_engine.core.settings",
    "planara_engine.domain",
    "planara_engine.domain.building",
    "planara_engine.domain.plot",
    "planara_engine.domain.snapshot",
    "planara_engine.engine",
    "planara_engine.engine.registry",
    "planara_engine.engine.rule_engine",
    "planara_engine.geometry",
    "planara_engine.geometry.normalize",
    "planara_engine.geometry.operations",
    "planara_engine.persistence",
    "planara_engine.persistence.database",
    "planara_engine.persistence.projects",
    "planara_engine.persistence.reports",
    "planara_engine.persistence.repository",
    "planara_engine.reporting",
    "planara_engine.reporting.archive",
    "planara_engine.reporting.diff",
    "planara_engine.reporting.diff_html",
    "planara_engine.reporting.html_renderer",
    "planara_engine.rules",
    "planara_engine.rules.loader",
    "planara_engine.rules.schema",
    # --- uvicorn internals ---
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    # --- bcrypt native extension ---
    "bcrypt",
    "bcrypt._bcrypt",
    # --- email MIME (pulled in by httpx / multipart) ---
    "email.mime",
    "email.mime.text",
    "email.mime.multipart",
    "email.mime.base",
    # --- pydantic ---
    "pydantic",
    "pydantic_settings",
    # --- sqlmodel / sqlalchemy ---
    "sqlmodel",
    "sqlalchemy.dialects.sqlite",
    # --- multipart ---
    "multipart",
    "python_multipart",
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [os.path.join(ENGINE_PKG, "cli.py")],
    pathex=[SRC_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Not needed at runtime; saves ~20 MB
        "tkinter",
        "matplotlib",
        "scipy",
        "PIL",
        "IPython",
        "notebook",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="planara-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    # Disable UPX for native extensions that break when compressed
    upx_exclude=["_bcrypt*", "*.pyd", "*.dll"],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=["_bcrypt*", "*.pyd", "*.dll"],
    name="planara-engine",
)
