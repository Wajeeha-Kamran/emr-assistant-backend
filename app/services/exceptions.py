class SessionNotFoundError(Exception):
    """Raised when a session doesn't exist or isn't owned by the authenticated doctor."""
    pass

class SOAPValidationError(Exception):
    """Raised when the generated draft does not meet structural requirements (e.g. strict 4 sections)."""
    pass

class SOAPNoteAlreadySignedError(Exception):
    """Raised when attempting to overwrite or regenerate a draft for a session whose note is already SIGNED."""
    pass

class TranscriptNotReadyError(Exception):
    """Raised when attempting to generate a SOAP note but the transcript is missing or not yet completed."""
    pass

class SOAPSectionNotFoundError(Exception):
    """Raised when a specific SOAP section cannot be found for a note."""
    pass

class CodeSuggestionTimeoutError(Exception):
    """Raised when code suggestion inference exceeds NLP_TIMEOUT_SECONDS.

    A domain exception rather than an HTTPException because this is raised
    inside a background task, where there is no response to attach a status
    code to. The message is stored in SOAPNote.codes_generation_error.
    """
    pass
