"""Mute the default playback device while the microphone is open.

Music or a video playing through speakers reaches the mic and gets dictated.
Core Audio through raw ctypes COM, like clipboard.py: IMMDeviceEnumerator ->
default render endpoint -> IAudioEndpointVolume.GetMute/SetMute.
"""

import ctypes
import uuid

ole32 = ctypes.windll.ole32
ole32.CoCreateInstance.restype = ctypes.HRESULT

COINIT_APARTMENTTHREADED = 0x2
CLSCTX_ALL = 0x17
E_RENDER, E_CONSOLE = 0, 0

# vtable slots, IUnknown's three included
RELEASE = 2
GET_DEFAULT_AUDIO_ENDPOINT = 4  # IMMDeviceEnumerator
ACTIVATE = 3  # IMMDevice
SET_MUTE, GET_MUTE = 14, 15  # IAudioEndpointVolume


class GUID(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_ubyte * 16)]


def _guid(s: str) -> GUID:
    return GUID.from_buffer_copy(uuid.UUID(s).bytes_le)


CLSID_MMDEVICE_ENUMERATOR = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDEVICE_ENUMERATOR = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAUDIO_ENDPOINT_VOLUME = _guid("5CDF2C82-841E-4546-9722-0CF74078229A")


def _method(obj: ctypes.c_void_p, slot: int, restype=ctypes.HRESULT, *argtypes):
    """The COM method at vtable slot; an HRESULT restype raises OSError on failure."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[slot])


def set_mute(muted: bool) -> bool:
    """Mute or unmute the default playback device. Returns whether it was muted before.

    Raises OSError if there is no playback device or COM refuses.
    """
    # S_FALSE or RPC_E_CHANGED_MODE both mean COM is already up on this thread.
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    enum, device, volume = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    out = ctypes.POINTER(ctypes.c_void_p)
    try:
        ole32.CoCreateInstance(
            ctypes.byref(CLSID_MMDEVICE_ENUMERATOR),
            None,
            CLSCTX_ALL,
            ctypes.byref(IID_IMMDEVICE_ENUMERATOR),
            ctypes.byref(enum),
        )
        _method(enum, GET_DEFAULT_AUDIO_ENDPOINT, ctypes.HRESULT, ctypes.c_int, ctypes.c_int, out)(
            enum, E_RENDER, E_CONSOLE, ctypes.byref(device)
        )
        _method(
            device,
            ACTIVATE,
            ctypes.HRESULT,
            ctypes.POINTER(GUID),
            ctypes.c_uint,
            ctypes.c_void_p,
            out,
        )(device, ctypes.byref(IID_IAUDIO_ENDPOINT_VOLUME), CLSCTX_ALL, None, ctypes.byref(volume))
        was = ctypes.c_int()
        _method(volume, GET_MUTE, ctypes.HRESULT, ctypes.POINTER(ctypes.c_int))(
            volume, ctypes.byref(was)
        )
        _method(volume, SET_MUTE, ctypes.HRESULT, ctypes.c_int, ctypes.c_void_p)(
            volume, int(muted), None
        )
        return bool(was.value)
    finally:
        for obj in (volume, device, enum):
            if obj.value:
                _method(obj, RELEASE, ctypes.c_ulong)(obj)
