import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

project_root = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [(os.path.join(project_root, "config.toml"), ".")]
datas += collect_data_files("translator_app")
datas += collect_data_files("faster_whisper")
datas += collect_data_files("soundcard")
datas += collect_data_files("pypinyin")
datas += collect_data_files("anyascii")

binaries = collect_dynamic_libs("ctranslate2")
system32 = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32")
for runtime_dll in (
    "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll",
    "vcruntime140.dll", "vcruntime140_1.dll",
):
    runtime_path = os.path.join(system32, runtime_dll)
    if os.path.exists(runtime_path):
        binaries.append((runtime_path, "."))

hiddenimports = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("soundcard")
hiddenimports += collect_submodules("pypinyin")
hiddenimports += collect_submodules("anyascii")

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
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="RemotePlusTranslator",
)
