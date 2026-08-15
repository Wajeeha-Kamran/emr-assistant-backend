"""
Stitches the per-turn WAV files produced by scripts/synthesize_scripts.ps1 into
one consultation recording per script.

WHY A SECOND STEP
Windows' speech engine writes one file per utterance. Joining them here rather
than in PowerShell keeps the audio handling in Python, where the sample-rate
and channel checks below are straightforward and where a mismatch fails loudly
instead of producing a file that plays as noise.

PACING
The gap inserted between turns follows the same deliberate variation the human
recording guide asked for, so the synthetic set is comparable to the human one
rather than uniformly easy:

    script 1   1.00s   clear pause between turns
    script 2   0.08s   rapid exchange, almost no gap
    script 3   0.35s   normal pacing
    script 4   0.35s   normal pacing

The gaps are real silence, which is generous compared with human speech: no
overlap, no breath, no crosstalk. That generosity is the point of a control
condition, and it is the reason these numbers must never be reported as
real-world performance.

Usage, from the repository root:
    .\\.venv\\Scripts\\python.exe -m scripts.build_synthetic_audio
"""

import os
import re
import sys
import wave

PARTS_DIR = os.path.join("docs", "evidence", "synthetic", "parts")
OUT_DIR = os.path.join("docs", "evidence", "synthetic")

GAP_SECONDS = {1: 1.00, 2: 0.08, 3: 0.35, 4: 0.35}
DEFAULT_GAP = 0.35

PART_RE = re.compile(r"^s(\d+)_t(\d+)_(DOCTOR|PATIENT)\.wav$")


def main() -> None:
    if not os.path.isdir(PARTS_DIR):
        sys.exit(f"FATAL: {PARTS_DIR} not found. Run scripts\\synthesize_scripts.ps1 first.")

    parts = {}
    for name in os.listdir(PARTS_DIR):
        m = PART_RE.match(name)
        if m:
            parts.setdefault(int(m.group(1)), []).append(
                (int(m.group(2)), os.path.join(PARTS_DIR, name))
            )

    if not parts:
        sys.exit(f"FATAL: no turn files matched in {PARTS_DIR}.")

    for script in sorted(parts):
        turns = [path for _, path in sorted(parts[script])]
        out_path = os.path.join(OUT_DIR, f"consult_{script}.wav")

        params = None
        frames = []
        for path in turns:
            with wave.open(path, "rb") as w:
                p = w.getparams()
                if params is None:
                    params = p
                elif (p.nchannels, p.sampwidth, p.framerate) != (
                    params.nchannels, params.sampwidth, params.framerate
                ):
                    # Fail rather than concatenate mismatched audio, which
                    # would produce a file that sounds like static and would be
                    # blamed on the model rather than on this script.
                    sys.exit(
                        f"FATAL: {path} has format "
                        f"{p.nchannels}ch/{p.sampwidth*8}bit/{p.framerate}Hz, "
                        f"expected {params.nchannels}ch/{params.sampwidth*8}bit/"
                        f"{params.framerate}Hz."
                    )
                frames.append(w.readframes(w.getnframes()))

        gap = GAP_SECONDS.get(script, DEFAULT_GAP)
        silence = b"\x00" * int(gap * params.framerate) * params.sampwidth * params.nchannels

        with wave.open(out_path, "wb") as out:
            out.setparams(params)
            for i, chunk in enumerate(frames):
                out.writeframes(chunk)
                if i < len(frames) - 1:
                    out.writeframes(silence)

        with wave.open(out_path, "rb") as w:
            duration = w.getnframes() / float(w.getframerate())

        print(f"consult_{script}.wav  {len(turns):>3} turns  {duration:>6.1f}s  "
              f"{params.framerate}Hz  gap {gap}s")

    print(f"\nWritten to {OUT_DIR}")
    print("Next: .\\.venv\\Scripts\\python.exe -m scripts.evaluate_accuracy "
          "--audio-dir docs/evidence/synthetic")


if __name__ == "__main__":
    main()
