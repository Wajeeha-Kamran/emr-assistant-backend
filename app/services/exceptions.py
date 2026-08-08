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
