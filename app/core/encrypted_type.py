"""
Application-layer encryption for clinical text columns via SQLAlchemy TypeDecorator.

Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256) from the
`cryptography` package.  The key is read from settings.ENCRYPTION_KEY and
never leaves the application layer — the database stores only ciphertext
as bytea, so a raw SELECT or pg_dump reveals nothing.

Limitation: key rotation is not supported — a single static Fernet key is
used.  No MultiFernet.  Acceptable for a prototype; a production deployment
would need a key-rotation strategy.
"""

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import LargeBinary
from sqlalchemy.types import TypeDecorator


class DecryptionError(ValueError):
    """Raised when ciphertext cannot be decrypted (wrong key, corrupted data)."""
    pass


class EncryptedText(TypeDecorator):
    """
    Transparently encrypts/decrypts a Python str to/from database bytea.

    On write (process_bind_param): plaintext str → Fernet-encrypted bytes.
    On read  (process_result_value): encrypted bytes → plaintext str.
    None values pass through unchanged.
    """

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        from app.core.config import settings
        f = Fernet(settings.ENCRYPTION_KEY.encode())
        return f.encrypt(value.encode("utf-8"))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        from app.core.config import settings
        f = Fernet(settings.ENCRYPTION_KEY.encode())
        try:
            return f.decrypt(value).decode("utf-8")
        except InvalidToken as e:
            raise DecryptionError(
                "Cannot decrypt clinical text: wrong key or corrupted data"
            ) from e
