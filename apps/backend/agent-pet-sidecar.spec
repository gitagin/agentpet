from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata


backend_root = Path(SPECPATH)
hook_root = backend_root / "packaging" / "pyinstaller_hooks"

datas = [
    (str(backend_root / "migrations"), "migrations"),
    (str(backend_root / "app" / "resources" / "wiki" / "AGENTS.md"), "app/resources/wiki"),
    (str(backend_root / "app" / "services" / "wiki.py"), "app/services"),
]
for distribution in (
    "APScheduler",
    "SQLAlchemy",
    "fastapi",
    "langchain",
    "langchain-openai",
    "langgraph",
    "pydantic",
    "pydantic-settings",
    "python-multipart",
    "uvicorn",
):
    datas += copy_metadata(distribution)

hiddenimports = [
    # The local-vector path imports these lazily at runtime; keep them in the
    # frozen archive so --self-test exercises the same code as retrieval.
    "langchain_qdrant",
    "qdrant_client",
    "onnxruntime",
    "tokenizers",
    "numpy",
    "sqlalchemy.dialects.sqlite",
    "uvicorn.lifespan.on",
    "uvicorn.logging",
    "uvicorn.loops.asyncio",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
]

a = Analysis(
    [str(backend_root / "app" / "sidecar_entry.py")],
    pathex=[str(backend_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(hook_root)],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "bitsandbytes",
        "cv2",
        "kuzu",
        "langchain_classic",
        "langchain_community",
        "matplotlib",
        "numba",
        "pandas",
        "pyarrow",
        "pytest",
        "pytest_asyncio",
        "scipy",
        "sklearn",
        "torch",
        "transformers",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="agent-pet-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="agent-pet-sidecar",
)
