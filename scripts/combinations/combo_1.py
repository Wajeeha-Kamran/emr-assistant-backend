"""
Combination 1 - Whisper medium + pyannote 3.1.

Asks one question: how much of the transcription error is the model being
small? medium is roughly ten times the parameters of base.en and correspondingly
slower on a CPU, so a gain here has to be weighed against the time it costs.

Run from the repository root:
    .venv\Scripts\python.exe scripts/combinations/combo_1.py
"""
from common import Combination, run

COMBINATION = Combination(
    number=1,
    asr="whisper",
    asr_model="medium",
    diarizer="pyannote",
    why="A larger Whisper. Does more accuracy come from a bigger model?",
    hyper={
        "whisper_model": 'medium (769M)',
        "language": 'en',
        "word_timestamps": True,
        "diarizer": 'pyannote/speaker-diarization-3.1',
        "num_speakers": 2,
        "smoothing": 'majority of 3 neighbouring words',
        "doctor_identification": 'question-count majority vote',
        "device": 'cpu',
    },
)

if __name__ == "__main__":
    run(COMBINATION)
