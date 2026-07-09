import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

project_root = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [(os.path.join(project_root, "config.toml"), ".")]
datas += collect_data_files("translator_app")
datas += collect_data_files("faster_whisper")
datas += collect_data_files("soundcard")

binaries = collect_dynamic_libs("ctranslate2")
binaries += collect_dynamic_libs("onnxruntime")

hiddenimports = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("webview")
hiddenimports += collect_submodules("soundcard")

a = Analysis(
    [os.path.join(project_root, "launcher.py")],
    pathex=[project_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "tkinter", "matplotlib", "IPython", "notebook",
        "torch", "transformers", "accelerate", "sentencepiece", "safetensors",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RemotePlusTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="RemotePlusTranslator",
)
