"""Helper: lower this process to Low integrity and run a command.
辅助脚本：将本进程降为 Low 完整性后执行命令。

Usage: python _low_integrity.py -- COMMAND...

The process lowers its own token to Windows Mandatory Low integrity, then
runs the command via subprocess. Low integrity processes cannot write to
Medium integrity objects (the default for all user files) -- the kernel
blocks it at the syscall level, even os.chmod/attrib -R cannot undo it.
本进程降为 Low 完整性后用 subprocess 执行命令。Low 进程无法写入 Medium
对象（用户文件默认值）——内核在 syscall 层阻止，os.chmod/attrib 也无法解除。
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes

TOKEN_ADJUST_DEFAULT = 0x0080
TOKEN_QUERY = 0x0008
SE_GROUP_INTEGRITY = 0x00000020
TOKEN_INTEGRITY_LEVEL = 25
LOW_INTEGRITY_SID = "S-1-16-4096"


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


def _setup_ctypes() -> tuple:
    advapi32 = ctypes.windll.advapi32
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.ConvertStringSidToSidW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi32.GetLengthSid.restype = wintypes.DWORD
    advapi32.SetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    advapi32.SetTokenInformation.restype = wintypes.BOOL
    return advapi32, kernel32


def lower_integrity() -> None:
    """Lower this process to Low integrity. Irreversible.
    将本进程降为 Low 完整性。不可逆。"""
    advapi32, kernel32 = _setup_ctypes()

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        TOKEN_ADJUST_DEFAULT | TOKEN_QUERY,
        ctypes.byref(token),
    ):
        raise ctypes.WinError()

    sid_ptr = ctypes.c_void_p()
    try:
        if not advapi32.ConvertStringSidToSidW(LOW_INTEGRITY_SID, ctypes.byref(sid_ptr)):
            raise ctypes.WinError()
        try:
            label = TOKEN_MANDATORY_LABEL()
            label.Label.Sid = sid_ptr
            label.Label.Attributes = SE_GROUP_INTEGRITY
            sid_len = advapi32.GetLengthSid(sid_ptr)
            if not advapi32.SetTokenInformation(
                token,
                TOKEN_INTEGRITY_LEVEL,
                ctypes.byref(label),
                ctypes.sizeof(label) + sid_len,
            ):
                raise ctypes.WinError()
        finally:
            kernel32.LocalFree(sid_ptr)
    finally:
        kernel32.CloseHandle(token)


def main() -> int:
    args = sys.argv[1:]
    if "--" not in args:
        print("usage: _low_integrity.py -- COMMAND...", file=sys.stderr)
        return 2

    sep = args.index("--")
    command = " ".join(args[sep + 1 :])
    if not command:
        return 0

    try:
        lower_integrity()
    except OSError as e:
        print(f"Failed to lower integrity: {e}", file=sys.stderr)
        return 1

    result = subprocess.run(command, shell=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
