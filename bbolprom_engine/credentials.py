"""User-owned OpenAI key in Windows Credential Manager, never in app files.

No environment-variable or plaintext-file fallback. The generic credential is
local to this Windows user and does not roam. Python strings cannot be reliably
zeroed; this protects storage, not a compromised user account or process memory.
"""
from __future__ import annotations
import ctypes
import os
import re

TARGET = 'Bbolprom/OpenAI/APIKey/v1'
_NOT_FOUND = 1168


class CredentialError(ValueError):
    """Messages contain no key, native error detail or submitted field value."""


def validate_key(key):
    if not isinstance(key, str) or not re.fullmatch(r'sk-[A-Za-z0-9_-]{16,512}', key):
        raise CredentialError('OpenAI 키 형식을 확인하세요. 키는 표시하거나 파일에 저장하지 않습니다.')
    return key


DWORD = ctypes.c_uint32
BYTE = ctypes.c_ubyte


class FILETIME(ctypes.Structure):
    _fields_ = [('low', DWORD), ('high', DWORD)]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [('Flags', DWORD), ('Type', DWORD), ('TargetName', ctypes.c_wchar_p),
        ('Comment', ctypes.c_wchar_p), ('LastWritten', FILETIME),
        ('CredentialBlobSize', DWORD), ('CredentialBlob', ctypes.POINTER(BYTE)),
        ('Persist', DWORD), ('AttributeCount', DWORD), ('Attributes', ctypes.c_void_p),
        ('TargetAlias', ctypes.c_wchar_p), ('UserName', ctypes.c_wchar_p)]


class WindowsCredentialStore:
    def __init__(self, *, _dll=None, _last_error=None):
        self._dll = _dll
        self._last_error = _last_error or getattr(ctypes, 'get_last_error', lambda: 0)
        if self._dll is None and os.name == 'nt':
            try:
                self._dll = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
            except OSError:
                pass
        if self._dll is not None:
            self._dll.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), DWORD]
            self._dll.CredWriteW.restype = ctypes.c_int32
            self._dll.CredReadW.argtypes = [ctypes.c_wchar_p, DWORD, DWORD,
                ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
            self._dll.CredReadW.restype = ctypes.c_int32
            self._dll.CredDeleteW.argtypes = [ctypes.c_wchar_p, DWORD, DWORD]
            self._dll.CredDeleteW.restype = ctypes.c_int32
            self._dll.CredFree.argtypes = [ctypes.c_void_p]
            self._dll.CredFree.restype = None

    @property
    def supported(self):
        return self._dll is not None

    def _require(self):
        if not self.supported:
            raise CredentialError('Windows 보안 보관함을 사용할 수 없어 키 저장·API 호출을 중단했습니다.')

    def save(self, key):
        self._require()
        encoded = validate_key(key).encode('ascii')
        blob = (BYTE * len(encoded)).from_buffer_copy(encoded)
        entry = CREDENTIALW(Type=1, TargetName=TARGET,
            CredentialBlobSize=len(encoded), CredentialBlob=blob,
            Persist=2, UserName='Bbolprom OpenAI')
        try:
            if not self._dll.CredWriteW(ctypes.byref(entry), 0):
                raise CredentialError('Windows 보안 보관함에 키를 저장하지 못했습니다.')
        finally:
            ctypes.memset(blob, 0, len(blob))

    def read(self):
        self._require()
        entry = ctypes.POINTER(CREDENTIALW)()
        if not self._dll.CredReadW(TARGET, 1, 0, ctypes.byref(entry)):
            if self._last_error() == _NOT_FOUND:
                return None
            raise CredentialError('Windows 보안 보관함에서 키를 읽지 못했습니다.')
        try:
            size = entry.contents.CredentialBlobSize
            if not 19 <= size <= 515 or not entry.contents.CredentialBlob:
                raise CredentialError('보관된 키 형식을 확인할 수 없습니다. 키를 교체하세요.')
            try:
                return validate_key(ctypes.string_at(entry.contents.CredentialBlob, size).decode('ascii'))
            except UnicodeError:
                raise CredentialError('보관된 키 형식을 확인할 수 없습니다. 키를 교체하세요.') from None
        finally:
            self._dll.CredFree(entry)

    def present(self):
        return bool(self.read()) if self.supported else False

    def delete(self):
        self._require()
        if not self._dll.CredDeleteW(TARGET, 1, 0) and self._last_error() != _NOT_FOUND:
            raise CredentialError('Windows 보안 보관함에서 키를 삭제하지 못했습니다.')
