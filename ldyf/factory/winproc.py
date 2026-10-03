"""Process facts the production layer needs and the standard library does not give.

Windows only where it has to be (`ctypes` against kernel32), with a plain
fallback elsewhere so the pure-Python parts of the factory still import and test
on any machine. Nothing here is third-party: the dependency lock is unchanged.

  * `process_identity(pid)`    creation time of a live process, or None. A lock
                               that names (pid, creation time) cannot be fooled
                               by a recycled pid.
  * `KillOnCloseJob`           a Win32 job object. Every child the factory spawns
                               (SUMO, ffmpeg, powershell) joins it, and the job
                               kills them when the factory process dies -- also
                               when it is killed with TerminateProcess, which is
                               the one death no `finally` can answer.
  * `process_memory()`         peak working set and open handle count of this process.
  * `find_processes(...)`      processes by image name with their command lines, used
                               to reap SUMO instances an earlier, killed run orphaned.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.GetCurrentProcess.restype = wintypes.HANDLE
    _k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    _k32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                wintypes.DWORD, ctypes.c_void_p]

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _EXT_LIMIT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BASIC_LIMIT), ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class _PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def _filetime(ft: Any) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def process_identity(pid: int) -> int | None:
    """Creation time (FILETIME ticks) of the live process `pid`; None when it is gone.

    On a non-Windows host the pid alone is probed and 0 is returned for 'alive'."""
    if pid <= 0:
        return None
    if not IS_WINDOWS:
        try:
            os.kill(pid, 0)
            return 0
        except OSError:
            return None
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        code = wintypes.DWORD()
        if not _k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != STILL_ACTIVE:
            return None
        c, e, k, u = (wintypes.FILETIME() for _ in range(4))
        if not _k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
            return None
        return _filetime(c)
    finally:
        _k32.CloseHandle(h)


def own_identity() -> int:
    return process_identity(os.getpid()) or 0


class KillOnCloseJob:
    """A job object that kills every process in it when the last handle closes.

    `adopt()` puts THIS process in the job; children started afterwards inherit
    membership. If the factory is itself already inside a job that forbids nesting
    (some launchers), `adopted` stays False and the production layer falls back to
    reaping orphans by command line."""

    def __init__(self) -> None:
        self.adopted = False
        self._h = None
        if not IS_WINDOWS:
            return
        h = _k32.CreateJobObjectW(None, None)
        if not h:
            return
        info = _EXT_LIMIT()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _k32.SetInformationJobObject(h, JobObjectExtendedLimitInformation, ctypes.byref(info),
                                            ctypes.sizeof(info)):
            _k32.CloseHandle(h)
            return
        self._h = h

    def adopt(self) -> bool:
        if self._h and _k32.AssignProcessToJobObject(self._h, _k32.GetCurrentProcess()):
            self.adopted = True
        return self.adopted

    def peak_memory_bytes(self) -> int | None:
        """Peak memory committed by any ONE process of the job group, summed as the
        job reports it (`PeakJobMemoryUsed`): the factory plus SUMO plus ffmpeg."""
        if not self._h or not self.adopted:
            return None
        info = _EXT_LIMIT()
        if not _k32.QueryInformationJobObject(self._h, JobObjectExtendedLimitInformation,
                                              ctypes.byref(info), ctypes.sizeof(info), None):
            return None
        return int(info.PeakJobMemoryUsed)


def process_memory() -> dict[str, int | None]:
    """Peak working set and handle count of this process (None where unmeasurable)."""
    if not IS_WINDOWS:
        return {"peak_working_set_bytes": None, "handles": None}
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(pmc)
    me = _k32.GetCurrentProcess()
    peak = int(pmc.PeakWorkingSetSize) if psapi.GetProcessMemoryInfo(me, ctypes.byref(pmc), pmc.cb) else None
    n = wintypes.DWORD()
    handles = int(n.value) if _k32.GetProcessHandleCount(me, ctypes.byref(n)) else None
    return {"peak_working_set_bytes": peak, "handles": handles}


def find_processes(image_name: str) -> list[dict[str, Any]]:
    """Processes called `image_name` with pid, parent pid and command line.

    One PowerShell/CIM query (about a second); only called when a run starts, to find
    SUMO instances a killed run left behind. Empty when the query itself fails."""
    if not IS_WINDOWS:
        return []
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='%s'\" | "
          "Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress" % image_name)
    try:
        run = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=60)
        text = run.stdout.strip()
        if run.returncode != 0 or not text:
            return []
        rows = json.loads(text)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    if isinstance(rows, dict):
        rows = [rows]
    return [{"pid": int(r["ProcessId"]), "ppid": int(r["ParentProcessId"]),
             "command_line": r.get("CommandLine") or ""} for r in rows]


def kill_pid(pid: int) -> bool:
    """Terminate one process by pid (used only on orphans the reaper has identified)."""
    try:
        run = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True,
                             timeout=30)
        return run.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class ExclusiveHold:
    """Open `path` with NO sharing (Windows) for the life of the context: nothing else can read,
    write, rename over or delete it. This is how an antivirus scan or a program that locked a file
    looks to the factory; used by the fault tests."""

    def __init__(self, path: str) -> None:
        self.path, self._h = str(path), None

    def __enter__(self) -> "ExclusiveHold":
        if not IS_WINDOWS:
            raise OSError("exclusive holds are only modelled on Windows")
        _k32.CreateFileW.restype = wintypes.HANDLE
        _k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        h = _k32.CreateFileW(self.path, 0x80000000 | 0x40000000, 0, None, 3, 0x80, None)
        if h in (None, wintypes.HANDLE(-1).value):
            raise OSError(ctypes.get_last_error(), f"cannot hold {self.path}")
        self._h = h
        return self

    def __exit__(self, *exc: object) -> None:
        if self._h:
            _k32.CloseHandle(self._h)
            self._h = None


def alternate_streams(path: str) -> list[str]:
    """Names of NTFS alternate data streams on a file (other than the unnamed one). A stream is
    invisible to a directory listing, to `sha256_file` and to the package manifest, so a package that
    must list everything it holds has to look for them. Empty on other platforms."""
    if not IS_WINDOWS:
        return []

    class _FindStream(ctypes.Structure):
        _fields_ = [("StreamSize", ctypes.c_longlong), ("cStreamName", ctypes.c_wchar * (260 + 36))]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.FindFirstStreamW.restype = wintypes.HANDLE
    k.FindFirstStreamW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.FindNextStreamW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    k.FindClose.argtypes = [wintypes.HANDLE]
    data = _FindStream()
    h = k.FindFirstStreamW(os.path.abspath(path), 0, ctypes.byref(data), 0)
    if h in (None, wintypes.HANDLE(-1).value):
        return []
    names = []
    try:
        while True:
            if data.cStreamName != "::$DATA":
                names.append(data.cStreamName)
            if not k.FindNextStreamW(h, ctypes.byref(data)):
                break
    finally:
        k.FindClose(h)
    return names
