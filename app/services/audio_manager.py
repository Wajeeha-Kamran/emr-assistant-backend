import os
import uuid
import shutil
from fastapi import UploadFile, HTTPException, status
from tinytag import TinyTag
from app.core.config import settings
from app.models.audio import AudioMetadata

# WAV has never had one agreed MIME type. Windows reports "audio/wave",
# browsers usually send "audio/wav", older tooling sends "audio/x-wav", and
# "audio/vnd.wave" is the IANA registration. All four name the same format.
#
# Found during the Module 9.2 manual API run on 15 Aug 2026: uploading a .wav
# from Windows was rejected with "Unsupported file type: audio/wave" while the
# identical file passed from the test suite, which sets the header itself. The
# automated tests could not have caught this — they never exercise a real
# client's content-type negotiation. A .NET MAUI client on Windows would have
# hit the same rejection.
ALLOWED_CONTENT_TYPES = [
    # WAV, all spellings in circulation
    "audio/wav", "audio/wave", "audio/x-wav", "audio/vnd.wave", "audio/x-pn-wav",
    # MP3
    "audio/mpeg", "audio/mp3",
    # MP4 / M4A
    "audio/mp4", "audio/x-m4a", "audio/m4a",
    # Others
    "audio/ogg", "audio/webm",
    # Some clients upload recordings under a video container type
    "video/webm", "video/mp4",
]

class AudioManager:
    @staticmethod
    def save_and_validate_audio(session_id: int, file: UploadFile) -> AudioMetadata:
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type: {file.content_type}"
            )
            
        # Ensure dir exists
        os.makedirs(settings.AUDIO_STORAGE_DIR, exist_ok=True)
        
        # Determine extension from filename
        ext = ""
        if file.filename and "." in file.filename:
            ext = "." + file.filename.rsplit(".", 1)[1].lower()
            
        safe_filename = f"session_{session_id}_{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(settings.AUDIO_STORAGE_DIR, safe_filename)
        
        # Save file to disk
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to save audio file")
            
        # Validate duration and format
        try:
            tag = TinyTag.get(file_path)
            duration_seconds = tag.duration or 0.0
        except Exception:
            os.remove(file_path)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or corrupt audio file")
            
        if duration_seconds > 1800:
            os.remove(file_path)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Audio exceeds maximum allowed duration of 30 minutes (got {duration_seconds}s)"
            )
            
        return AudioMetadata(
            session_id=session_id,
            file_path=file_path,
            duration_seconds=duration_seconds,
            format=file.content_type
        )
