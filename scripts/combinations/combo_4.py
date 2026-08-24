"""
Combination 4 - Whisper base.en + pyannote 3.1, with noise.

The same as combination 0 with white noise mixed in at 10 dB, which is roughly
a busy clinic. Isolates how much of the accuracy depends on a quiet room. The
noise is generated from a fixed seed so the run is repeatable.

Run from the repository root:
    .venv\Scripts\python.exe scripts/combinations/combo_4.py
"""
from common import Combination, run

COMBINATION = Combination(
    number=4,
    asr="whisper",
    asr_model="base.en",
    diarizer="pyannote",
    noise_db=10,
    why="The current system again, with background noise added.",
    hyper={
        "whisper_model": 'base.en (74M)',
        "language": 'en',
        "word_timestamps": True,
        "diarizer": 'pyannote/speaker-diarization-3.1',
        "num_speakers": 2,
        "noise": 'additive white Gaussian, 10 dB SNR, seed 1244',
        "doctor_identification": 'question-count majority vote',
        "device": 'cpu',
    },
)

if __name__ == "__main__":
    run(COMBINATION)
