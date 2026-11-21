"""Opt-in, local 3.4-second PCM startup soundtrack with no bundled media."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import logging
from pathlib import Path
from wave import Error as WaveError, open as read_wave

from gui.startup_audio_worker import AudioRequestRejected, prepare_async, retain_native

_PROFILE = "belly-hd-first-055-156-3400"
_AUDIO = "hd-laugh-first-055-3400/laugh-fade-a.wav"
_SAMPLE_RATE = 48_000
_SAMPLES = 163_200
_LOG = logging.getLogger("cet.startup.audio")


class AudioUnavailable(RuntimeError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError("Unexpected size")
    return raw


def _local_pcm(assets: Path, contract: Path) -> bytes:
    spec = json.loads(_bounded(contract, 8192).decode("utf-8-sig"))
    if (
        spec["profile"] != _PROFILE or spec["file"] != _AUDIO
        or spec["native_video_frames"] != [55, 156]
        or spec["duration_ms"] != 3400 or spec["sample_rate"] != _SAMPLE_RATE
        or spec["samples"] != _SAMPLES or spec["channels"] != 1
    ):
        raise ValueError("Unexpected startup audio profile")
    base = assets.resolve(strict=True)
    path = base / _AUDIO
    if path.resolve(strict=True) != path:
        raise ValueError("Audio path points outside its expected location")
    raw = _bounded(path, 768 * 1024)
    if sha256(raw).hexdigest() != spec["sha256"]:
        raise ValueError("Audio digest mismatch")
    with read_wave(BytesIO(raw), "rb") as source:
        if (source.getframerate(), source.getnframes(), source.getnchannels(),
            source.getsampwidth(), source.getcomptype()) != (_SAMPLE_RATE, _SAMPLES, 1, 2, "NONE"):
            raise ValueError("Unexpected PCM format")
        pcm = source.readframes(_SAMPLES)
    if len(pcm) != _SAMPLES * 2:
        raise ValueError("Truncated PCM")
    return pcm


class _Factory:
    def __init__(self, pcm, loader):
        self._pcm = pcm
        self._loader = loader

    def __call__(self, _path):
        # This adapter supports the approved 3.4-second native profile only.
        raise AudioRequestRejected("pcm-media-rejected")

    def prepare(self):
        return prepare_async(self._loader, self._pcm)


def optional_sound_factory(assets: Path, contract: Path, *, load_backend=None):
    """Read and validate local bytes; never initialize a backend or send samples."""
    try:
        pcm = _local_pcm(assets, contract)
    except (OSError, WaveError, EOFError, KeyError, TypeError, ValueError, RecursionError):
        _LOG.info("local-startup-audio-missing-or-rejected")
        return None
    return _Factory(pcm, _load_prepared_pcm if load_backend is None else load_backend)


def _load_prepared_pcm():
    """Bind Windows functions on the audio worker, with native heap ownership."""
    import ctypes as c

    class Format(c.Structure):
        _pack_=1
        _fields_=[("tag",c.c_ushort),("channels",c.c_ushort),("rate",c.c_uint32),
                  ("bytes_per_sec",c.c_uint32),("alignment",c.c_ushort),("bits",c.c_ushort),("extra",c.c_ushort)]

    class Header(c.Structure):
        _fields_=[("buffer",c.c_void_p),("length",c.c_uint32),("recorded",c.c_uint32),
                  ("user",c.c_size_t),("flags",c.c_uint32),("loops",c.c_uint32),
                  ("next",c.c_void_p),("reserved",c.c_size_t)]

    winmm=c.WinDLL("winmm")
    kernel=c.WinDLL("kernel32")
    H=c.c_void_p
    HP=c.POINTER(Header)
    def wire(library,name,result,*args):
        call=getattr(library,name);call.argtypes=args;call.restype=result
        return call
    def wave(name,*args):
        return wire(winmm,name,c.c_uint32,*args)
    heap=wire(kernel,"GetProcessHeap",H)()
    allocate=wire(kernel,"HeapAlloc",H,H,c.c_uint32,c.c_size_t)
    free=wire(kernel,"HeapFree",c.c_int,H,c.c_uint32,H)
    open_pcm=wave("waveOutOpen",c.POINTER(H),c.c_uint32,c.POINTER(Format),c.c_size_t,c.c_size_t,c.c_uint32)
    prepare=wave("waveOutPrepareHeader",H,HP,c.c_uint32)
    write=wave("waveOutWrite",H,HP,c.c_uint32)
    reset=wave("waveOutReset",H)
    unprepare=wave("waveOutUnprepareHeader",H,HP,c.c_uint32)
    close=wave("waveOutClose",H)
    header_bytes=c.sizeof(Header)
    if not heap or c.sizeof(Format)!=18 or header_bytes!=(48 if c.sizeof(H)==8 else 32):
        raise RuntimeError("invalid-waveout-abi")

    class PreparedWave:
        def __init__(self,pcm):
            self.handle=H()
            self.address=None
            self.hdr=None
            self.prepared=False
            self.must_reset=False
            fmt=Format(1,1,48000,96000,2,16,0)
            try:
                if open_pcm(c.byref(self.handle),0xffffffff,c.byref(fmt),0,0,0)!=0:
                    raise AudioUnavailable("backend-unavailable")
                self.address=allocate(heap,8,header_bytes+len(pcm))
                if not self.address:
                    raise AudioUnavailable("pcm-buffer-unavailable")
                # No Python ctypes object owns the block. In-use native
                # storage can survive GC and Python teardown until OS exit.
                self.hdr=Header.from_address(self.address)
                self.hdr.buffer=self.address+header_bytes
                self.hdr.length=len(pcm)
                c.memmove(self.hdr.buffer,pcm,len(pcm))
                if prepare(self.handle,c.byref(self.hdr),header_bytes)!=0:
                    raise AudioUnavailable("backend-unavailable")
                self.prepared=True
            except Exception:
                try:
                    if not self.stop():
                        retain_native(self)
                except Exception:
                    retain_native(self)
                raise
            _LOG.info("pcm-device-prepared-no-samples-submitted")

        def dispatch_pcm(self,claim,still_current):
            if self.must_reset or not self.handle or not self.prepared:
                return False
            submit=write
            args=(self.handle,c.byref(self.hdr),header_bytes)
            if not claim():
                return False
            # Even after a software commit, a cancel/deadline here can
            # suppress delivery. After this last guard the native attempt
            # may be in flight; nothing on the GUI waits for it.
            self.must_reset=True
            if not still_current():
                self.must_reset=False
                return False
            result=submit(*args)
            if result!=0:
                raise AudioUnavailable("backend-declined")
            return True

        def stop(self):
            # Two bounded attempts; never free when driver ownership is
            # unresolved. The worker quarantines this device on refusal.
            for _ in range(2):
                if self.handle and self.must_reset:
                    reset(self.handle)
                if self.prepared:
                    if unprepare(self.handle,c.byref(self.hdr),header_bytes)!=0:
                        continue
                    self.prepared=False
                if self.handle:
                    if close(self.handle)!=0:
                        continue
                    self.handle=H()
                if self.address:
                    if not free(heap,0,self.address):
                        continue
                    self.hdr=None
                    self.address=None
                return True
            return False

    class Adapter:
        @staticmethod
        def prepare_pcm(pcm):
            return PreparedWave(pcm)
    return Adapter()
