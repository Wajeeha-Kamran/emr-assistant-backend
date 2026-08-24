"""
Combination 3 - Parakeet TDT 0.6B v2 + pyannote 3.1.

Replaces Whisper entirely. Parakeet is NVIDIA's recogniser and reports strong
English results; this checks whether that holds on consultation audio. Needs
NeMo, so it runs in Colab.

Run from the repository root:
    .venv\Scripts\python.exe scripts/combinations/combo_3.py
"""
from common import Combination, run

COMBINATION = Combination(
    number=3,
    asr="parakeet",
    asr_model="nvidia/parakeet-tdt-0.6b-v2",
    diarizer="pyannote",
    why="NVIDIA's speech recogniser instead of Whisper.",
    hyper={
        "asr_model": 'nvidia/parakeet-tdt-0.6b-v2 (600M)',
        "timestamps": True,
        "diarizer": 'pyannote/speaker-diarization-3.1',
        "num_speakers": 2,
        "smoothing": 'majority of 3 neighbouring words',
        "doctor_identification": 'question-count majority vote',
        "device": 'cpu',
    },
)

if __name__ == "__main__":
    run(COMBINATION)
