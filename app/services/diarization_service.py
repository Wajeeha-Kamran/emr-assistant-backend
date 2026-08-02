from typing import List, Dict, Any
from app.core.config import settings

class DiarizationService:
    @staticmethod
    def diarize_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Labels each transcript segment with a speaker role: DOCTOR or PATIENT.
        
        Rules:
        - The first speaker defaults to DOCTOR (since they initiate the session).
        - For subsequent segments: if the pause duration between previous segment's end
          and current segment's start is >= DIARIZATION_PAUSE_THRESHOLD, we assume the
          speaker role alternates. Otherwise, the current speaker maintains the same role.
          
        Note: This is a turn-based pause heuristic suited for a lightweight prototype,
        aligned with the English-only scope by design.
        """
        if not segments:
            return []

        diarized_segments = []
        current_role = "DOCTOR"
        threshold = settings.DIARIZATION_PAUSE_THRESHOLD

        # Process the first segment
        first_segment = segments[0]
        diarized_segments.append({
            "start": first_segment.get("start"),
            "end": first_segment.get("end"),
            "text": first_segment.get("text", ""),
            "speaker_role": current_role
        })

        previous_end = first_segment.get("end")

        # Process subsequent segments
        for seg in segments[1:]:
            start = seg.get("start")
            end = seg.get("end")
            text = seg.get("text", "")

            # If either start or previous_end is missing, we maintain the speaker
            if start is not None and previous_end is not None:
                pause = start - previous_end
                if pause >= threshold:
                    # Alternate roles
                    current_role = "PATIENT" if current_role == "DOCTOR" else "DOCTOR"

            diarized_segments.append({
                "start": start,
                "end": end,
                "text": text,
                "speaker_role": current_role
            })

            # Update previous_end if the current segment has a valid end timestamp
            if end is not None:
                previous_end = end

        return diarized_segments
