"""Build the Windows installer with one command, from the repo root:

    .venv/Scripts/python.exe packaging/build.py

Steps: packaging/make_icon.py -> PyInstaller (packaging/fernal.spec, clean build into build/ and dist/ at the
repo root) -> Inno Setup (packaging/fernal.iss) -> packaging/Output/Fernal-Setup-<version>.exe.

Needs PyInstaller in the virtual environment and Inno Setup 6 with its Korean language file. The compiler is
found through the ISCC environment variable (full path to ISCC.exe) or the usual install folders.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging"
OUTPUT = PKG / "Output"


def find_iscc() -> Path:
    env = os.environ.get("ISCC")
    if env:
        if Path(env).is_file():
            return Path(env)
        sys.exit(f"error: the ISCC environment variable points to {env!r}, which is not a file")
    bases = [(os.environ.get("LOCALAPPDATA"), "Programs"), (os.environ.get("ProgramFiles(x86)"), ""),
             (os.environ.get("ProgramFiles"), "")]
    candidates = [Path(base) / sub / "Inno Setup 6" / "ISCC.exe" for base, sub in bases if base]
    for path in candidates:
        if path.is_file():
            return path
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    sys.exit("error: Inno Setup 6 compiler (ISCC.exe) not found.\n"
             "Install Inno Setup 6 (https://jrsoftware.org/isinfo.php) or set the ISCC environment variable to\n"
             "the full path of ISCC.exe. Looked in:\n" + "\n".join(f"  {p}" for p in candidates))


def run(step: str, cmd: list) -> None:
    print(f"\n== {step}\n   {' '.join(str(c) for c in cmd)}", flush=True)
    subprocess.run([str(c) for c in cmd], cwd=ROOT, check=True)


def folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def mib(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MiB"


def main() -> None:
    iscc = find_iscc()
    started = time.time()
    run("1/3 icon", [sys.executable, PKG / "make_icon.py"])
    run("2/3 PyInstaller", [sys.executable, "-m", "PyInstaller", PKG / "fernal.spec", "--noconfirm", "--clean",
                            "--distpath", ROOT / "dist", "--workpath", ROOT / "build"])
    run("3/3 Inno Setup", [iscc, "/Qp", PKG / "fernal.iss"])

    setups = [p for p in OUTPUT.glob("Fernal-Setup-*.exe") if p.stat().st_mtime >= started - 1]
    if not setups:
        sys.exit("error: Inno Setup finished but no new Fernal-Setup-*.exe was written to " + str(OUTPUT))
    setup = max(setups, key=lambda p: p.stat().st_mtime)
    print(f"\nSetup:        {setup}")
    print(f"Setup size:   {mib(setup.stat().st_size)}")
    print(f"dist/Fernal:  {mib(folder_size(ROOT / 'dist' / 'Fernal'))} (installed size)")


if __name__ == "__main__":
    main()
