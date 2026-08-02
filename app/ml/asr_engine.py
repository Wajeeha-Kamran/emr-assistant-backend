from typing import Protocol, runtime_checkable


class ASRError(Exception):
    """Raised when any ASR engine fails to transcribe audio."""
    pass


@runtime_checkable
class ASREngine(Protocol):
    """
    Protocol defining the interface all ASR engines must implement.

    Any class with a matching transcribe() method satisfies this protocol
    (structural subtyping — no explicit inheritance required).
    """

    def transcribe(self, audio_path: str) -> dict:
        """
        Transcribes the given audio file.

        Args:
            audio_path: Absolute or relative path to the audio file.

        Returns:
            A dictionary with shape:
            {
                "text": str,                    # Full transcript text
                "segments": [                   # Per-segment detail
                    {"start": float, "end": float, "text": str},
                    ...
                ]
            }

        Raises:
            ASRError: If the file is missing, unreadable, or transcription fails.
        """
        ...
