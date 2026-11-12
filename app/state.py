"""State machine aplikasi: IDLE / LIVE / ESTOP."""
from __future__ import annotations

from enum import Enum


class State(Enum):
    IDLE = "IDLE"
    LIVE = "LIVE"
    ESTOP = "E-STOP"


class StateMachine:
    """
    IDLE  --tangan terdeteksi-->  LIVE  --tidak ada tangan > timeout-->  IDLE
    E-STOP bisa kapan pun: robot menahan posisi. Tekan lagi (Space / tombol) untuk lepas -> IDLE.
    """

    def __init__(self, idle_timeout_s: float):
        self.idle_timeout_s = idle_timeout_s
        self.state = State.IDLE
        self.last_hand_t: float | None = None
        self.changed = True     # True satu kali setelah transisi (untuk aksi "on enter")

    def _go(self, s: State) -> None:
        if s != self.state:
            self.state = s
            self.changed = True

    def toggle_estop(self) -> None:
        self._go(State.IDLE if self.state == State.ESTOP else State.ESTOP)

    def update(self, hand_visible: bool, now: float) -> State:
        if hand_visible:
            self.last_hand_t = now
        if self.state == State.IDLE and hand_visible:
            self._go(State.LIVE)
        elif self.state == State.LIVE and not hand_visible:
            if self.last_hand_t is None or now - self.last_hand_t > self.idle_timeout_s:
                self._go(State.IDLE)
        return self.state

    def pop_changed(self) -> bool:
        c, self.changed = self.changed, False
        return c
