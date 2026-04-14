"""py2app build configuration for Tifaw.app."""

from setuptools import setup

APP = ["tifaw/app.py"]

DATA_FILES = [
    (
        "frontend",
        [
            "frontend/index.html",
            "frontend/app.js",
            "frontend/styles.css",
            "frontend/icon.png",
            "frontend/icon.icns",
        ],
    ),
]

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "frontend/icon.icns",
    "packages": [
        "tifaw",
        "fastapi",
        "uvicorn",
        "httpx",
        "watchdog",
        "pymupdf",
        "pydantic",
        "pydantic_settings",
        "yaml",
        "PIL",
        "aiosqlite",
        "webview",
        "multipart",
        "starlette",
        "anyio",
        "sniffio",
        "idna",
        "certifi",
        "httpcore",
        "click",
        "h11",
        "typing_extensions",
    ],
    "includes": [
        "objc",
        "AppKit",
        "Foundation",
        "Vision",
    ],
    "frameworks": [],
    "plist": {
        "CFBundleName": "Tifaw",
        "CFBundleDisplayName": "Tifaw",
        "CFBundleIdentifier": "com.guaali.tifaw",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "NSHumanReadableCopyright": "Tifaw — Your laptop's story, powered by local AI.",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
    },
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
