import pytest
from app.services.diarization_service import DiarizationService
from app.core.config import settings

def test_diarize_empty_segments():
    result = DiarizationService.diarize_segments([])
    assert result == []

def test_diarize_single_segment():
    segments = [{"start": 0.0, "end": 2.5, "text": "Hello doctor."}]
    result = DiarizationService.diarize_segments(segments)
    
    assert len(result) == 1
    assert result[0]["speaker_role"] == "DOCTOR"
    assert result[0]["text"] == "Hello doctor."

def test_diarize_pause_below_threshold():
    # Pause is 1.0 seconds, which is less than the threshold (1.5)
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hello doctor."},
        {"start": 3.0, "end": 5.0, "text": "How can I help you today?"}
    ]
    result = DiarizationService.diarize_segments(segments)
    
    assert len(result) == 2
    assert result[0]["speaker_role"] == "DOCTOR"
    assert result[1]["speaker_role"] == "DOCTOR" # Maintained speaker

def test_diarize_pause_above_threshold():
    # Pause is 2.0 seconds, which is greater than the threshold (1.5)
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hello doctor."},
        {"start": 4.0, "end": 6.0, "text": "My head hurts."}
    ]
    result = DiarizationService.diarize_segments(segments)
    
    assert len(result) == 2
    assert result[0]["speaker_role"] == "DOCTOR"
    assert result[1]["speaker_role"] == "PATIENT" # Alternated speaker

def test_diarize_multiple_turns():
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Start consultation."}, # DOCTOR
        {"start": 2.5, "end": 4.0, "text": "Adding detail."}, # Pause 0.5 (< 1.5) -> DOCTOR
        {"start": 6.0, "end": 8.0, "text": "Patient speaking."}, # Pause 2.0 (>= 1.5) -> PATIENT
        {"start": 8.5, "end": 9.5, "text": "Still patient."}, # Pause 0.5 (< 1.5) -> PATIENT
        {"start": 12.0, "end": 14.0, "text": "Doctor replies."} # Pause 2.5 (>= 1.5) -> DOCTOR
    ]
    result = DiarizationService.diarize_segments(segments)
    
    assert len(result) == 5
    assert result[0]["speaker_role"] == "DOCTOR"
    assert result[1]["speaker_role"] == "DOCTOR"
    assert result[2]["speaker_role"] == "PATIENT"
    assert result[3]["speaker_role"] == "PATIENT"
    assert result[4]["speaker_role"] == "DOCTOR"
    
    for r in result:
        assert r["speaker_role"] is not None
