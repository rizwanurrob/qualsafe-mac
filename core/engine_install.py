"""Install the analysis engine (torch, transformers, sentence-transformers) from inside the program.

Automatic suggested codes for survey answers need three large packages the installers do not carry. They used
to be added from a terminal into the program's own folder. That cannot work for a signed macOS app (writing
into the bundle breaks its signature, and /Applications may not be writable), and it is a lot to ask of a
non-technical user on any system. So the engine goes into a per-user folder instead, outside the program, and the program
adds that folder to its import path when it starts:

    Windows   %LOCALAPPDATA%\\QualSafe\\engine\\py312
    macOS     ~/Library/Application Support/QualSafe/engine/py312
    Linux     ~/.local/share/qualsafe/engine/py312        (or $XDG_DATA_HOME)

`QUALSAFE_ENGINE_DIR` overrides it. The folder is named for the Python version, so an upgraded interpreter
never loads another version's compiled files.

* `activate()`        put the folder on the import path (and on PYTHONPATH for child processes); idempotent
* `installed()`       whether the three packages can be found
* `install(progress)` run pip into the folder, reporting each line; raises `EngineInstallError` on failure

Nothing here imports torch: finding out whether torch exists must not cost seconds and a gigabyte of memory.
The install is the only step that uses the network for the engine itself (model weights are a separate,
explicit download), and it never touches the user's data.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

#: What the transformer path needs, as pip names and as import names.
REQUIREMENTS = ("torch>=2.2,<3.0", "transformers>=4.40,<5.0", "sentence-transformers>=2.7,<4.0")
IMPORT_NAMES = ("torch", "transformers", "sentence_transformers")

#: Packages the program already ships. The engine's own dependencies are held to these versions, so the
#: copy that gets installed beside them is the same one: whichever is found first on the import path works.
PINNED_FROM_THE_PROGRAM = ("numpy", "scipy", "scikit-learn", "pandas", "huggingface-hub", "requests", "tqdm",
                           "PyYAML", "packaging", "pillow")

CPU_TORCH_INDEX = "https://download.pytorch.org/whl/cpu"


class EngineInstallError(RuntimeError):
    """The install did not finish. The message is for a person; `.log` has pip's last lines."""

    def __init__(self, message: str, log: str = "") -> None:
        super().__init__(message)
        self.log = log


# -- where it lives ---------------------------------------------------------------------------------

def engine_dir(system: str = "", home: Optional[Path] = None) -> Path:
    """The per-user folder the engine is installed into (not created here)."""
    override = os.environ.get("QUALSAFE_ENGINE_DIR", "").strip()
    if override:
        return Path(override)
    system = system or sys.platform
    home = home or Path.home()
    if system == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "QualSafe" / "engine"
    elif system == "darwin":
        base = home / "Library" / "Application Support" / "QualSafe" / "engine"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "qualsafe" / "engine"
    return base / f"py{sys.version_info[0]}{sys.version_info[1]}"


def activate(directory: Optional[Path] = None) -> bool:
    """Make the installed engine importable. True if a folder was added. Safe to call any number of times."""
    folder = Path(directory) if directory else engine_dir()
    if not folder.is_dir():
        return False
    text = str(folder)
    changed = False
    if text not in sys.path:
        sys.path.append(text)       # after the program's own packages: their copies win, the engine fills gaps
        changed = True
    existing = os.environ.get("PYTHONPATH", "")
    if text not in existing.split(os.pathsep):
        os.environ["PYTHONPATH"] = existing + os.pathsep + text if existing else text   # child processes
    if changed:
        importlib.invalidate_caches()
    return changed


def missing() -> List[str]:
    """Import names of the engine packages that cannot be found right now."""
    return [name for name in IMPORT_NAMES if importlib.util.find_spec(name) is None]


def installed() -> bool:
    return not missing()


# -- what to install -------------------------------------------------------------------------------

def platform_constraints(system: str = "", machine: str = "") -> List[str]:
    """Version limits that depend on the computer.

    The app is built on NumPy 1.x, so the engine must not pull NumPy 2. PyTorch stopped publishing macOS wheels
    for Intel after 2.2.2, so on an Intel Mac that is the one release pip can be asked for."""
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    limits = ["numpy>=1.24,<2.0"]
    if system == "darwin" and machine in ("x86_64", "amd64", "i386"):
        limits.append("torch==2.2.2")
    return limits


def program_pins() -> List[str]:
    """`name==version` for each package the program already has, so pip does not choose a different one."""
    pins = []
    for name in PINNED_FROM_THE_PROGRAM:
        try:
            pins.append(f"{name}=={importlib.metadata.version(name)}")
        except importlib.metadata.PackageNotFoundError:
            continue
    return pins


def python_for_pip() -> str:
    """The interpreter to run pip with. On Windows the program runs as pythonw.exe (no console window), whose
    sibling python.exe is the one that can show pip's output."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").is_file():
        return str(exe.parent / "python.exe")
    return str(exe)


def steps(system: str = "", machine: str = "", pins: Optional[Iterable[str]] = None) -> List[Dict[str, object]]:
    """The pip runs, in order: [{"label", "args", "packages"}].

    Windows and Linux fetch torch from PyTorch's CPU-only index (the default one carries the CUDA build, which
    is several gigabytes larger and useless without an NVIDIA card), then the rest from PyPI. A Mac's PyPI wheels
    are already the CPU and Apple-silicon builds, so one run does it."""
    system = system or sys.platform
    constraints = platform_constraints(system, machine)
    held = list(pins) if pins is not None else program_pins()
    # --no-compile: pip would otherwise write a .pyc for every .py as it installs (about 5 times slower
    # on SciPy alone, measured: 157 s against 32 s; the whole engine took 50 minutes). Python makes them on first import.
    base = ["--upgrade", "--no-compile", "--no-warn-script-location", "--disable-pip-version-check",
            "--progress-bar", "off"]
    if system in ("win32", "linux"):
        torch_spec = "torch==2.2.2" if "torch==2.2.2" in constraints else REQUIREMENTS[0]
        return [
            {"label": "PyTorch (the CPU build)", "args": [*base, "--index-url", CPU_TORCH_INDEX], "packages": [torch_spec]},
            {"label": "transformers and sentence-transformers", "args": base,
             "packages": [REQUIREMENTS[1], REQUIREMENTS[2], *constraints, *held]},
        ]
    return [{"label": "the analysis engine", "args": base, "packages": [*REQUIREMENTS, *constraints, *held]}]


def install_command(step: Dict[str, object], target: Path, python: str = "") -> List[str]:
    return [python or python_for_pip(), "-m", "pip", "install", "--target", str(target),
            *step["args"], *step["packages"]]  # type: ignore[misc]


# -- doing it --------------------------------------------------------------------------------------

#: Packages pip copies into the engine folder because it ignores what the program already has, with their
#: import names. The program's own copies are the ones that load (the engine folder is last on the path), so
#: these only cost about 300 MB and install time.
DUPLICATED_BY_PIP = {"numpy": ("numpy", "numpy.libs"), "scipy": ("scipy", "scipy.libs"), "pandas": ("pandas",),
                     "scikit-learn": ("sklearn",)}


def prune_duplicates(target: Path) -> List[str]:
    """Remove from `target` the copies of packages the program itself ships (see DUPLICATED_BY_PIP).

    Only a package the program really has is removed: if it is missing here, the copy in the engine folder is
    the one that is needed and is kept. Returns what was removed."""
    import shutil

    removed: List[str] = []
    for package, folders in DUPLICATED_BY_PIP.items():
        try:
            importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
        names = list(folders)
        names += [p.name for p in Path(target).glob(f"{package.replace('-', '_')}-*.dist-info")]
        for name in names:
            path = Path(target) / name
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                removed.append(name)
    return removed

Progress = Callable[[str], None]


def _stream(command: List[str], progress: Optional[Progress], env: Optional[Dict[str, str]] = None) -> List[str]:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               env=env, creationflags=flags)
    tail: List[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        if not line:
            continue
        tail.append(line)
        del tail[:-40]
        if progress:
            progress(line)
    code = process.wait()
    if code != 0:
        raise EngineInstallError(f"pip stopped with exit code {code}", "\n".join(tail))
    return tail


def verify(python: str, target: Path) -> None:
    """Import the three packages in a fresh interpreter, with the engine folder on the path."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(target) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("HF_HUB_OFFLINE", "1")
    env.setdefault("TRANSFORMERS_OFFLINE", "1")
    code = "import torch, transformers, sentence_transformers; print('engine ok', torch.__version__)"
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    done = subprocess.run([python, "-c", code], capture_output=True, text=True, env=env, creationflags=flags)
    if done.returncode != 0:
        raise EngineInstallError("The packages installed but would not load.", (done.stderr or done.stdout)[-1500:])


def install(progress: Optional[Progress] = None, target: Optional[Path] = None, python: str = "",
            stream: Callable[..., List[str]] = _stream, check: bool = True) -> Dict[str, object]:
    """Install the engine into `target` (default: `engine_dir()`), then make it importable here.

    `progress` is called with each line pip prints and with a short line when a step starts. Returns
    {"ok": True, "target": path}; raises `EngineInstallError` otherwise (the folder is left as it is, so
    running it again carries on rather than starting over)."""
    folder = Path(target) if target else engine_dir()
    interpreter = python or python_for_pip()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise EngineInstallError(f"Could not create {folder}: {error}") from error

    plan = steps()
    for number, step in enumerate(plan, 1):
        if progress:
            progress(f"Step {number} of {len(plan)}: installing {step['label']}")
        stream(install_command(step, folder, interpreter), progress)
    removed = prune_duplicates(folder)
    if removed and progress:
        progress("Removed copies of " + ", ".join(sorted(removed)) + " that the program already has")
    if check:
        if progress:
            progress("Checking that it loads")
        verify(interpreter, folder)
    activate(folder)
    return {"ok": True, "target": str(folder)}
