"""Reliable discovery and validation of installed MetaTrader 5 terminals.

Windows installations do not always register themselves under MetaQuotes, and a
broker can install several terminals side by side. Discovery therefore combines
the filesystem, the registry and running processes, and every candidate is
validated as a real terminal executable. Nothing here connects to a terminal.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

TERMINAL_EXE_NAMES = frozenset({"terminal64.exe", "terminal.exe"})
_META_TRADER_DIR = re.compile(r"(metatrader|meta trader|mt5)", re.IGNORECASE)
_COMPANY_HINTS = {
    "metatrader 5": "MetaQuotes",
    "metatrader 5 exness": "Exness",
    "metatrader 5 icmarkets": "IC Markets",
    "metatrader 5 pepperstone": "Pepperstone",
    "metatrader 5 xm": "XM",
    "metatrader 5 oanda": "OANDA",
}


@dataclass(frozen=True, slots=True)
class TerminalCandidate:
    path: str
    name: str
    company: str | None = None
    build: int | None = None
    source: str = "filesystem"
    running: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "name": self.name,
            "company": self.company,
            "build": self.build,
            "source": self.source,
            "running": self.running,
        }


def normalize_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip('"')
    if not text:
        return None
    try:
        return str(Path(text).expanduser().resolve(strict=False))
    except OSError:
        return str(Path(text).expanduser().absolute())


def validate_terminal_executable(value: str | Path | None) -> tuple[bool, str | None]:
    """Return (valid, reason) without launching anything."""

    path = normalize_path(value)
    if not path:
        return False, "No terminal executable path was provided."
    candidate = Path(path)
    if candidate.name.lower() not in TERMINAL_EXE_NAMES:
        return False, f"'{candidate.name}' is not a MetaTrader 5 terminal executable (terminal64.exe or terminal.exe)."
    if not candidate.exists():
        return False, f"Terminal executable not found: {path}"
    if not candidate.is_file():
        return False, f"Terminal path is not a file: {path}"
    return True, None


def _company_for(path: Path) -> str | None:
    parent = path.parent.name.strip()
    lowered = parent.lower()
    for hint, company in _COMPANY_HINTS.items():
        if lowered.startswith(hint):
            return company
    if lowered.startswith("metatrader"):
        suffix = re.sub(r"^metatrader\s*5?", "", parent, flags=re.IGNORECASE).strip(" -_")
        return suffix or "MetaQuotes"
    return None


def _candidate(path: str | Path, source: str, running: bool = False, company: str | None = None) -> TerminalCandidate | None:
    ok, _ = validate_terminal_executable(path)
    if not ok:
        return None
    resolved = Path(str(normalize_path(path)))
    return TerminalCandidate(
        path=str(resolved),
        name=resolved.parent.name or resolved.name,
        company=company or _company_for(resolved),
        source=source,
        running=running,
    )


def _program_files_roots() -> list[Path]:
    roots: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        value = os.environ.get(variable)
        if value:
            roots.append(Path(value))
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        roots.append(Path(local_appdata) / "Programs")
    return roots


def _scan_filesystem() -> list[TerminalCandidate]:
    found: list[TerminalCandidate] = []
    for root in _program_files_roots():
        if not root.exists():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            # Only inspect plausible MetaTrader folders, plus one level of
            # vendor subdivision (e.g. Program Files\Broker\MetaTrader 5).
            candidates = [entry]
            if not _META_TRADER_DIR.search(entry.name):
                try:
                    candidates.extend(child for child in entry.iterdir() if child.is_dir())
                except OSError:
                    continue
            for candidate_dir in candidates:
                if not _META_TRADER_DIR.search(candidate_dir.name):
                    continue
                for exe_name in TERMINAL_EXE_NAMES:
                    candidate = _candidate(candidate_dir / exe_name, "filesystem")
                    if candidate:
                        found.append(candidate)
    return found


def _scan_registry() -> list[TerminalCandidate]:
    found: list[TerminalCandidate] = []
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return found

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"Software\MetaQuotes\Terminal") as key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    if subkey_name.lower() in {"common", "settings"}:
                        continue
                    try:
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            for value_name in ("Path", "InstallPath", "Executable"):
                                try:
                                    raw, _ = winreg.QueryValueEx(subkey, value_name)
                                except OSError:
                                    continue
                                candidate_path = Path(str(raw))
                                if candidate_path.is_dir():
                                    candidate_path = candidate_path / "terminal64.exe"
                                candidate = _candidate(candidate_path, "registry")
                                if candidate:
                                    found.append(candidate)
                    except OSError:
                        continue
        except OSError:
            continue
    return found


def _scan_processes() -> list[TerminalCandidate]:
    found: list[TerminalCandidate] = []
    try:
        import psutil
    except ImportError:  # pragma: no cover - psutil is a runtime dependency
        return found

    for process in psutil.process_iter(["name", "exe"]):
        try:
            name = (process.info.get("name") or "").lower()
            if name not in TERMINAL_EXE_NAMES:
                continue
            exe = process.info.get("exe")
            candidate = _candidate(exe or "", "process", running=True)
            if candidate:
                found.append(candidate)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return found


def discover_terminals(extra_paths: list[str] | None = None) -> list[TerminalCandidate]:
    """Return every distinct MetaTrader 5 terminal executable, running first."""

    candidates: list[TerminalCandidate] = []
    for raw in extra_paths or []:
        candidate = _candidate(raw, "configured")
        if candidate:
            candidates.append(candidate)
    candidates.extend(_scan_processes())
    candidates.extend(_scan_registry())
    candidates.extend(_scan_filesystem())

    deduped: dict[str, TerminalCandidate] = {}
    for candidate in candidates:
        key = os.path.normcase(candidate.path)
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = candidate
        else:
            deduped[key] = TerminalCandidate(
                path=existing.path,
                name=existing.name,
                company=existing.company or candidate.company,
                build=existing.build or candidate.build,
                source=existing.source if existing.source != "filesystem" else candidate.source,
                running=existing.running or candidate.running,
            )

    return sorted(deduped.values(), key=lambda item: (not item.running, item.name.lower(), item.path.lower()))
