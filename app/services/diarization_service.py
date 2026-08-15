import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

DOCTOR = "DOCTOR"
PATIENT = "PATIENT"

# Sliding-window parameters, used by the "window" method only.
WINDOW_SECONDS = 1.5
HOP_SECONDS = 0.5


class DiarizationService:
    """
    Labels transcript content as DOCTOR or PATIENT.

    FOUR METHODS, in the order they were built and measured against four
    scripted consultations on 15 Aug 2026. All are retained because the
    progression is this project's design-evolution record.

      method       mean speaker accuracy   why it was superseded
      ---------------------------------------------------------------------
      pause                        68.9%   Never fired. Whisper leaves no gaps
                                           between segments (93 gaps, mean
                                           0.006s, max 0.560s), so the
                                           threshold was unreachable at any
                                           value. Every segment was labelled
                                           DOCTOR, which also left every SOAP
                                           Subjective section empty.
      embedding                    66.0%   Fingerprints whole Whisper segments.
                                           Fails when a segment contains two
                                           speakers, which is routine.
      window                       48.8%   Correct approach — found 15 turns
                                           against 16 real ones — but fragile
                                           clustering and label assignment.
      pyannote (default)              —    Purpose-built pipeline: VAD,
                                           embeddings, clustering and overlap
                                           handling developed together.

    Module 2.2's revision note deferred the pyannote decision until diarization
    accuracy could be measured against real recordings. It was measured, it
    fell short, and this is that upgrade.
    """

    # -- public API -------------------------------------------------------

    @staticmethod
    def diarize_segments(segments: List[Dict[str, Any]],
                         audio_path: Optional[str] = None) -> List[Dict[str, Any]]:
        if not segments:
            return []

        method = getattr(settings, "DIARIZATION_METHOD", "pyannote")

        if method in ("pyannote", "window", "embedding") and not audio_path:
            logger.warning(
                "Voice-based diarization requested but no audio_path was supplied; "
                "falling back to the deprecated pause heuristic, which does not work."
            )
            return DiarizationService._diarize_by_pause(segments)

        if method == "pyannote":
            try:
                return DiarizationService._diarize_by_pyannote(segments, audio_path)
            except Exception as e:
                logger.error(
                    "pyannote diarization failed (%s: %s); falling back to the "
                    "sliding-window method.", type(e).__name__, e
                )
                method = "window"

        if method == "window":
            if not any(s.get("words") for s in segments):
                logger.warning(
                    "Window diarization needs word timestamps but none were found."
                )
                method = "embedding"
            else:
                try:
                    return DiarizationService._diarize_by_window(segments, audio_path)
                except Exception as e:
                    logger.error("Window diarization failed (%s: %s).",
                                 type(e).__name__, e)
                    method = "embedding"

        if method == "embedding":
            try:
                return DiarizationService._diarize_by_embedding(segments, audio_path)
            except Exception as e:
                logger.error(
                    "Embedding diarization failed (%s: %s); falling back to the "
                    "deprecated pause heuristic. Speaker labels will be unreliable.",
                    type(e).__name__, e
                )

        return DiarizationService._diarize_by_pause(segments)

    # -- shared helpers ---------------------------------------------------

    @staticmethod
    def _collect_words(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        words: List[Dict[str, Any]] = []
        for seg in segments:
            for w in seg.get("words") or []:
                start, end = w.get("start"), w.get("end")
                text = (w.get("word") or w.get("text") or "").strip()
                if start is None or end is None or not text:
                    continue
                words.append({"start": float(start), "end": float(end), "text": text})
        words.sort(key=lambda w: w["start"])
        return words

    @staticmethod
    def _smooth(labels: List[Any]) -> List[Any]:
        """
        Remove single-item flips. A lone word disagreeing with both neighbours
        is nearly always a boundary artefact rather than a real interjection.
        """
        for i in range(1, len(labels) - 1):
            if labels[i - 1] == labels[i + 1] and labels[i] != labels[i - 1]:
                labels[i] = labels[i - 1]
        return labels

    @staticmethod
    def _group(words: List[Dict[str, Any]], labels: List[Any],
               doctor_label: Any) -> List[Dict[str, Any]]:
        """Group consecutive same-speaker words into turns."""
        out: List[Dict[str, Any]] = []
        cur_text = [words[0]["text"]]
        cur_label = labels[0]
        cur_start, cur_end = words[0]["start"], words[0]["end"]

        for w, lab in zip(words[1:], labels[1:]):
            if lab == cur_label:
                cur_text.append(w["text"])
                cur_end = w["end"]
            else:
                out.append({
                    "start": cur_start, "end": cur_end,
                    "text": " ".join(cur_text).strip(),
                    "speaker_role": DOCTOR if cur_label == doctor_label else PATIENT,
                })
                cur_text = [w["text"]]
                cur_label = lab
                cur_start, cur_end = w["start"], w["end"]

        out.append({
            "start": cur_start, "end": cur_end,
            "text": " ".join(cur_text).strip(),
            "speaker_role": DOCTOR if cur_label == doctor_label else PATIENT,
        })
        return out

    @staticmethod
    def _identify_doctor(words: List[Dict[str, Any]], labels: List[Any]) -> Any:
        """
        Decide which speaker cluster is the clinician.

        WHAT THIS REPLACES, and why the old rule was wrong:
        the previous rule was `doctor_label = labels[0]` — whoever speaks the
        first word is the doctor. Measured on 15 Aug 2026, script 3 separated
        almost perfectly (every turn boundary correct) yet scored 7.3%, because
        pyannote gave the three-word opening fragment "Hi there, what" its own
        short turn and put it in the wrong cluster. One mislabelled fragment
        inverted the whole consultation. Anchoring a transcript's identity on a
        single word has no redundancy: it is wrong or right, with nothing to
        outvote it.

        THE RULE USED INSTEAD:
        the speaker who asks the questions is the clinician. Clinical
        history-taking is question-driven by structure — the doctor elicits,
        the patient reports — which is how the consultation is described in the
        SRS use cases themselves. Counted over the four reference scripts the
        separation is not marginal:

            script 1   doctor 7 questions   patient 0
            script 2   doctor 6             patient 1
            script 3   doctor 5             patient 0
            script 4   doctor 7             patient 1

        This is a majority vote over every question in the consultation rather
        than a single-point decision, so no one mislabelled fragment can invert
        the result. It has no tunable threshold, so there is nothing here that
        could be quietly fitted to these particular recordings.

        HONEST LIMITATION:
        a consultation where the patient asks more questions than the clinician
        would invert. That is uncommon but not impossible. Speaking first is
        kept as the tie-break for when neither speaker asks anything — a very
        short exchange, or audio where Whisper emits no question marks.
        """
        questions: Dict[Any, int] = {}
        for word, label in zip(words, labels):
            if word["text"].endswith("?"):
                questions[label] = questions.get(label, 0) + 1

        if questions:
            best = max(questions.values())
            winners = [lab for lab, n in questions.items() if n == best]
            if len(winners) == 1:
                logger.info("Doctor identified by question count: %s", questions)
                return winners[0]

        logger.info(
            "Question counts did not separate the speakers (%s); falling back "
            "to whoever speaks first.", questions or "none found"
        )
        return labels[0]

    # -- pyannote method (default) ---------------------------------------

    @staticmethod
    def _diarize_by_pyannote(segments: List[Dict[str, Any]],
                             audio_path: str) -> List[Dict[str, Any]]:
        from app.ml.pyannote_engine import PyannoteEngine

        turns: List[Tuple[float, float, str]] = (
            PyannoteEngine.get_instance().diarize(audio_path, num_speakers=2)
        )
        if not turns:
            raise ValueError("pyannote returned no speaker turns")

        words = DiarizationService._collect_words(segments)
        if not words:
            # No word timestamps: fall back to labelling whole Whisper segments
            # by whichever speaker turn overlaps each one the most.
            out = []
            for seg in segments:
                lab = DiarizationService._label_for(
                    (seg.get("start") or 0.0), (seg.get("end") or 0.0), turns
                )
                out.append(DiarizationService._labelled(
                    seg, DOCTOR if lab == turns[0][2] else PATIENT))
            return out

        labels = [
            DiarizationService._label_for(w["start"], w["end"], turns) for w in words
        ]
        labels = DiarizationService._smooth(labels)

        doctor_label = DiarizationService._identify_doctor(words, labels)

        out = DiarizationService._group(words, labels, doctor_label)
        n_doc = sum(1 for s in out if s["speaker_role"] == DOCTOR)
        logger.info("Diarization (pyannote): %d words -> %d turns "
                    "(%d DOCTOR / %d PATIENT)",
                    len(words), len(out), n_doc, len(out) - n_doc)
        return out

    @staticmethod
    def _label_for(start: float, end: float,
                   turns: List[Tuple[float, float, str]]) -> str:
        """Speaker whose turn overlaps [start, end] most; nearest if none do."""
        best_label, best_overlap = None, 0.0
        for t_start, t_end, label in turns:
            overlap = min(end, t_end) - max(start, t_start)
            if overlap > best_overlap:
                best_overlap, best_label = overlap, label
        if best_label is not None:
            return best_label

        mid = (start + end) / 2.0
        return min(
            turns,
            key=lambda t: min(abs(mid - t[0]), abs(mid - t[1])),
        )[2]

    # -- window method ----------------------------------------------------

    @staticmethod
    def _diarize_by_window(segments: List[Dict[str, Any]],
                           audio_path: str) -> List[Dict[str, Any]]:
        from app.ml.speaker_embedding_engine import (
            SpeakerEmbeddingEngine, cluster_into_two, SAMPLE_RATE,
        )

        engine = SpeakerEmbeddingEngine.get_instance()
        wav = engine.load_audio(audio_path)
        total = len(wav) / SAMPLE_RATE

        bounds, t = [], 0.0
        while t < total:
            bounds.append((t, min(t + WINDOW_SECONDS, total)))
            t += HOP_SECONDS

        rms = []
        for a, b in bounds:
            chunk = wav[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)]
            rms.append(float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0)
        rms_arr = np.asarray(rms)
        floor = 0.35 * float(np.median(rms_arr[rms_arr > 0])) if np.any(rms_arr > 0) else 0.0

        centres, embeddings = [], []
        for (a, b), energy in zip(bounds, rms):
            if energy < floor:
                continue
            emb = engine.embed_slice(wav, a, b)
            if emb is not None:
                centres.append((a + b) / 2.0)
                embeddings.append(emb)

        if len(embeddings) < 2:
            raise ValueError(f"only {len(embeddings)} window(s) fingerprinted")

        clusters = cluster_into_two(np.stack(embeddings))
        centres_arr = np.asarray(centres)

        words = DiarizationService._collect_words(segments)
        if not words:
            raise ValueError("no usable word timestamps")

        labels = [
            int(clusters[int(np.argmin(np.abs(centres_arr - (w["start"] + w["end"]) / 2.0)))])
            for w in words
        ]
        labels = DiarizationService._smooth(labels)
        return DiarizationService._group(words, labels, labels[0])

    # -- per-segment embedding method ------------------------------------

    @staticmethod
    def _diarize_by_embedding(segments: List[Dict[str, Any]],
                              audio_path: str) -> List[Dict[str, Any]]:
        from app.ml.speaker_embedding_engine import (
            SpeakerEmbeddingEngine, cluster_into_two,
        )

        engine = SpeakerEmbeddingEngine.get_instance()
        wav = engine.load_audio(audio_path)

        embeddings, indices = [], []
        for idx, seg in enumerate(segments):
            start, end = seg.get("start"), seg.get("end")
            if start is None or end is None:
                continue
            emb = engine.embed_slice(wav, start, end)
            if emb is not None:
                embeddings.append(emb)
                indices.append(idx)

        if len(embeddings) < 2:
            return [DiarizationService._labelled(s, DOCTOR) for s in segments]

        clusters = cluster_into_two(np.stack(embeddings))
        doctor_cluster = int(clusters[0])
        roles = {i: (DOCTOR if int(c) == doctor_cluster else PATIENT)
                 for i, c in zip(indices, clusters)}

        out, last = [], DOCTOR
        for idx, seg in enumerate(segments):
            role = roles.get(idx, last)
            last = role
            out.append(DiarizationService._labelled(seg, role))
        return out

    # -- deprecated pause method -----------------------------------------

    @staticmethod
    def _diarize_by_pause(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """DEPRECATED. Retained for the design-evolution record only."""
        threshold = settings.DIARIZATION_PAUSE_THRESHOLD
        out, role, prev_end = [], DOCTOR, None
        for seg in segments:
            start, end = seg.get("start"), seg.get("end")
            if prev_end is not None and start is not None:
                if start - prev_end >= threshold:
                    role = PATIENT if role == DOCTOR else DOCTOR
            out.append(DiarizationService._labelled(seg, role))
            if end is not None:
                prev_end = end
        return out

    # -- helper -----------------------------------------------------------

    @staticmethod
    def _labelled(seg: Dict[str, Any], role: str) -> Dict[str, Any]:
        return {
            "start": seg.get("start"),
            "end": seg.get("end"),
            "text": seg.get("text", ""),
            "speaker_role": role,
        }
