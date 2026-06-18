# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — builds the desktop app on the CURRENT OS.
#   macOS:    pyinstaller FuturesBot.spec      -> dist/Futures Trading Bot.app
#   Windows:  pyinstaller FuturesBot.spec      -> dist/Futures Trading Bot/...exe
# (You cannot cross-build; run on each OS, or use the GitHub Actions workflow.)
import os
import sys

from PyInstaller.utils.hooks import collect_submodules, collect_all

APP_NAME = "EXO"

binaries = []
datas = [
    ("server/static", "server/static"),     # dashboard assets
    ("config/config.yaml", "config"),        # default config (seeded on first run)
]

# Our packages use dynamic discovery (pkgutil/importlib), so collect submodules
# explicitly or PyInstaller's static analysis will miss the strategies/adapters.
hiddenimports = []
for pkg in ("strategies", "brokers", "data"):
    hiddenimports += collect_submodules(pkg)

# uvicorn / starlette pull their protocol stacks dynamically.
hiddenimports += [
    "uvicorn.logging", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "h11", "websockets", "anyio", "dotenv", "yaml", "aiohttp",
]

# tzdata: the value-area cockpit uses zoneinfo (ET sessions) — bundle the data so
# it works frozen, especially on Windows which has no system tz database.
try:
    tz_datas, tz_bin, tz_hidden = collect_all("tzdata")
    datas += tz_datas
    binaries += tz_bin
    hiddenimports += tz_hidden + ["tzdata"]
except Exception:
    pass

# pywebview is optional — collect it (and its backend) only if installed on the
# build machine. If absent, the app still works via the browser fallback.
try:
    import webview  # noqa: F401
    wv_datas, wv_binaries, wv_hidden = collect_all("webview")
    datas += wv_datas
    binaries += wv_binaries
    hiddenimports += wv_hidden
    if sys.platform == "darwin":
        hiddenimports += ["objc", "Foundation", "WebKit", "AppKit", "Cocoa", "Quartz"]
    elif sys.platform.startswith("win"):
        hiddenimports += ["clr", "webview.platforms.edgechromium", "webview.platforms.mshtml"]
except Exception:
    pass

icon = None
if sys.platform == "darwin" and os.path.exists("build/icon.icns"):
    icon = "build/icon.icns"
elif sys.platform.startswith("win") and os.path.exists("build/icon.ico"):
    icon = "build/icon.ico"

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # The packaged app needs none of the ML/data research stack at runtime — the
    # cockpit + rule strategies use plain math, and the ML meta-filter safely
    # passes through when these are absent. Excluding them keeps the app ~13MB
    # instead of ~200MB. (Run research tools from source with requirements-ml.txt.)
    excludes=[
        "pandas", "numpy", "scipy", "sklearn", "pyarrow", "databento",
        "lightgbm", "xgboost", "matplotlib", "IPython", "joblib", "research", "PIL",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=False,
    console=False,            # windowed app (no terminal window)
    icon=icon,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="com.exo.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "LSMinimumSystemVersion": "10.14",
        },
    )
