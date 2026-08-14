import os
import uuid
import shutil
from fastapi import UploadFile, HTTPException, status
from tinytag import TinyTag
from app.core.config import settings
from app.models.audio import AudioMetadata

ALLOWED_CONTENT_TYPES = [
    "audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", 
    "audio/ogg", "audio/webm", "audio/x-m4a", "audio/mp3", 
    "video/webm", "video/mp4"
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
