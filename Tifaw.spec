# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Tifaw.app."""

import os

block_cipher = None

a = Analysis(
    ["tifaw/app.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("frontend/index.html", "frontend"),
        ("frontend/app.js", "frontend"),
        ("frontend/styles.css", "frontend"),
        ("frontend/icon.png", "frontend"),
        ("frontend/icon.icns", "frontend"),
        ("tifaw", "tifaw"),
    ],
    hiddenimports=[
        "tifaw",
        "tifaw.main",
        "tifaw.config",
        "tifaw.app",
        "tifaw.llm.client",
        "tifaw.models.database",
        "tifaw.indexer.queue",
        "tifaw.indexer.pipeline",
        "tifaw.indexer.extractors",
        "tifaw.indexer.analyzer",
        "tifaw.watcher.observer",
        "tifaw.faces.detector",
        "tifaw.chat.agent",
        "tifaw.renamer.smart_rename",
        "tifaw.api.routes_status",
        "tifaw.api.routes_files",
        "tifaw.api.routes_search",
        "tifaw.api.routes_rename",
        "tifaw.api.routes_chat",
        "tifaw.api.routes_organize",
        "tifaw.api.routes_folders",
        "tifaw.api.routes_duplicates",
        "tifaw.api.routes_cleanup",
        "tifaw.api.routes_projects",
        "tifaw.api.routes_digest",
        "tifaw.api.routes_config",
        "tifaw.api.routes_faces",
        "tifaw.api.routes_overview",
        "tifaw.api.routes_photos",
        "tifaw.api.routes_documents",
        "tifaw.api.routes_onboarding",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "multipart",
        "multipart.multipart",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Tifaw",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch="arm64",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Tifaw",
)

app = BUNDLE(
    coll,
    name="Tifaw.app",
    icon="frontend/icon.icns",
    bundle_identifier="com.guaali.tifaw",
    info_plist={
        "CFBundleName": "Tifaw",
        "CFBundleDisplayName": "Tifaw",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "NSHumanReadableCopyright": "Tifaw — Your laptop's story, powered by local AI.",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
    },
)
