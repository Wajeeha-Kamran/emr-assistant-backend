"""
Combination 5 - Whisper base.en + Sortformer.  THE RECOMMENDATION.

The cheapest recogniser with the best separator. Earlier measurement put
Sortformer above 99% speaker accuracy down to 5 dB while pyannote collapsed to
12.4% on consult_2, and Sortformer costs 0.13x realtime on a CPU. If this
matches combination 2, the larger Whisper is not worth its cost. Needs NeMo,
so it runs in Colab.

Run from the repository root:
    .venv\Scripts\python.exe scripts/combinations/combo_5.py
"""
from common import Combination, run

COMBINATION = Combination(
    number=5,
    asr="whisper",
    asr_model="base.en",
    diarizer="sortformer",
    why="The cheapest recogniser with the best separator. This is the recommendation.",
    hyper={
        "whisper_model": 'base.en (74M)',
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
