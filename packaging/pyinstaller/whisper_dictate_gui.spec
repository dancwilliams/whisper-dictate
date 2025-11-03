# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

project_root = Path(__file__).resolve().parent.parent.parent
assets_dir = project_root / "assets"


def _collect_assets():
    for asset in assets_dir.glob("whisper_dictate_gui.*"):
        yield str(asset), f"assets/{asset.name}"


def _collect_nvidia_binaries():
    packages = [
        "nvidia.cuda_runtime",
        "nvidia.cublas",
        "nvidia.cudnn",
    ]
    for pkg_name in packages:
        try:
            for entry in collect_dynamic_libs(pkg_name):
                yield entry
        except Exception:
            # The Windows wheels ship these packages; keep the build resilient
            continue


datas = list(_collect_assets())
binaries = list(_collect_nvidia_binaries())
hiddenimports = sorted(
    set(
        collect_submodules("whisper_dictate")
        + collect_submodules("faster_whisper")
        + collect_submodules("pyautogui")
    )
)

block_cipher = None


a = Analysis(
    [str(project_root / "whisper_dictate" / "gui.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="whisper-dictate-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(assets_dir / "whisper_dictate_gui.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="whisper-dictate-gui",
)
