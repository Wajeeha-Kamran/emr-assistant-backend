"""
Combination 2 - Whisper medium + Sortformer.

The larger recogniser with the better separator - the most accurate combination
available, and the most expensive. Needs NeMo, so it runs in Colab.

Run from the repository root:
    .venv\Scripts\python.exe scripts/combinations/combo_2.py
"""
from common import Combination, run

COMBINATION = Combination(
    number=2,
    asr="whisper",
    asr_model="medium",
    diarizer="sortformer",
    why="Larger Whisper with the new speaker separator.",
    hyper={
        "whisper_model": 'medium (769M)',
        "language": 'en',
        "word_timestamps": True,
        "diarizer": 'nvidia/diar_sortformer_4spk-v1',
        "max_speakers": 4,
        "batch_size": 1,
        "postprocessing": 'NeMo defaults',
        "doctor_identification": 'question-count majority vote',
        "device": 'cpu',
    },
)

if __name__ == "__main__":
    run(COMBINATION)
