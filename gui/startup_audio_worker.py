"""One bounded audio job per process. GUI requests never call or wait for a driver."""
from __future__ import annotations

from threading import Condition, Lock, Thread
from time import monotonic
import logging

_LOG=logging.getLogger("cet.startup.audio")
_LOCK=Lock()
_ACTIVE=None
_QUARANTINE=[]
# We deliberately do not start a different audio job after an unsafe driver
# release. This retains every outstanding native owner until process exit.
SUBMIT_WINDOW_SECONDS=.035
READY_IDLE_SECONDS=2.
PLAY_LIMIT_SECONDS=3.8


class AudioRequestRejected(RuntimeError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason=reason


def retain_native(device):
    """Process-lifetime strong retention, including constructor failures."""
    with _LOCK:
        if not any(x is device for x in _QUARANTINE):
            _QUARANTINE.append(device)
    _LOG.warning("native-audio-release-unconfirmed; further prepared audio disabled")


def prepare_async(loader,pcm):
    """Reserve one generation; start/stop use only a brief control lock."""
    global _ACTIVE
    ticket=_Ticket(loader,pcm)
    with _LOCK:
        if _QUARANTINE:
            raise AudioRequestRejected("audio-driver-quarantined")
        if _ACTIVE is not None:
            raise AudioRequestRejected("audio-worker-busy")
        _ACTIVE=ticket
    try:
        Thread(target=ticket._run,name="CET startup PCM worker",daemon=True).start()
    except Exception:
        with _LOCK:
            if _ACTIVE is ticket:
                _ACTIVE=None
        raise AudioRequestRejected("audio-worker-unavailable") from None
    return ticket


class _Ticket:
    def __init__(self,loader,pcm):
        self._loader=loader
        self._pcm=pcm
        self._cv=Condition()
        self._ready=False
        self._cancelled=False
        self._deadline=None
        self._lease_committed=False
        self._released=False

    def play(self):
        with self._cv:
            if self._cancelled or self._released:
                raise AudioRequestRejected("pcm-generation-cancelled")
            if not self._ready:
                self._cancelled=True
                self._cv.notify_all()
                raise AudioRequestRejected("pcm-not-ready-at-first-frame")
            if self._deadline is not None:
                raise AudioRequestRejected("pcm-already-queued")
            self._deadline=monotonic()+SUBMIT_WINDOW_SECONDS
            self._cv.notify_all()
        return "pcm-submit-queued"

    def stop(self):
        # Never wait for a driver call. If the lease was already committed,
        # cancellation requests reset as soon as the worker can service it.
        with self._cv:
            self._cancelled=True
            self._cv.notify_all()
            return "cancel-in-flight" if self._lease_committed else "cancel-before-lease"

    def _current_locked(self):
        return (not self._cancelled and not self._released and
                self._deadline is not None and monotonic()<=self._deadline)

    def _claim_dispatch(self):
        # Software-only linearization point: cancel/deadline versus making
        # an irrevocable attempt to dispatch this generation. This does not
        # mean WinMM has been entered, let alone that samples are audible.
        with self._cv:
            if self._lease_committed or not self._current_locked():
                return False
            self._lease_committed=True
            return True

    def _still_dispatchable(self):
        # Last-chance guard, deliberately outside the native invocation.
        with self._cv:
            return self._lease_committed and self._current_locked()

    def _run(self):
        global _ACTIVE
        device=None
        try:
            with self._cv:
                if self._cancelled:
                    return
            backend=self._loader()
            with self._cv:
                if self._cancelled:
                    return
            device=backend.prepare_pcm(self._pcm)
            with self._cv:
                self._ready=not self._cancelled
                wake=monotonic()+READY_IDLE_SECONDS
                while self._deadline is None and not self._cancelled:
                    left=wake-monotonic()
                    if left<=0:
                        self._cancelled=True
                        break
                    self._cv.wait(left)
                pending=self._current_locked()
            # The adapter claims at the last practical software hand-off,
            # after building its arguments. Never hold the lock across I/O.
            submitted=pending and device.dispatch_pcm(self._claim_dispatch,self._still_dispatchable)
            if submitted:
                _LOG.info("pcm-driver-write-returned; audible-output-not-verified")
                end=monotonic()+PLAY_LIMIT_SECONDS
                with self._cv:
                    while not self._cancelled:
                        left=end-monotonic()
                        if left<=0:
                            break
                        self._cv.wait(left)
            else:
                _LOG.info("pcm-no-driver-write-returned; lease_committed=%s",self._lease_committed)
        except Exception:
            _LOG.warning("pcm-worker-failed; no audio retry")
        finally:
            if device is not None:
                try:
                    if device.stop() is not True:
                        retain_native(device)
                except Exception:
                    retain_native(device)
            with self._cv:
                self._released=True
                self._pcm=None
                self._cv.notify_all()
            with _LOCK:
                if _ACTIVE is self:
                    _ACTIVE=None
