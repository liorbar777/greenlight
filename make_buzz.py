#!/usr/bin/env python3
"""Generate buzz.wav — the long error buzzer played when the light turns red.

A harsh "BZZZZT" (think game-show wrong-answer): two slightly detuned low
square waves beating against each other, with a short fade-out so it doesn't
click. Stdlib only (wave + struct) so there's no build dependency. Re-run after
tweaking to regenerate the asset:  .venv/bin/python make_buzz.py
"""
import math
import os
import struct
import wave

RATE = 44100
DUR = 0.5           # seconds — short, sharp error buzz
F1, F2 = 150.0, 153.0   # detuned pair -> rough, beating buzzer texture
AMP = 0.38          # 0..1 headroom; loud enough to notice, not painful
FADE = 0.06         # seconds of fade-out to kill the end click
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "buzz.wav")


def square(freq, t):
    # sign() of a sine = square wave; harsh harmonics give the buzzer bite.
    return 1.0 if math.sin(2 * math.pi * freq * t) >= 0 else -1.0


def main():
    n = int(RATE * DUR)
    fade_n = int(RATE * FADE)
    frames = bytearray()
    for i in range(n):
        t = i / RATE
        s = 0.5 * square(F1, t) + 0.5 * square(F2, t)
        env = 1.0
        if i > n - fade_n:                      # linear fade-out tail
            env = max(0.0, (n - i) / fade_n)
        val = int(max(-1.0, min(1.0, s * AMP * env)) * 32767)
        frames += struct.pack("<h", val)
    with wave.open(OUT, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    print(f"wrote {OUT} ({n} frames, {DUR}s)")


if __name__ == "__main__":
    main()
