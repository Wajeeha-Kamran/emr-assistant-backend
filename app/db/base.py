from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

from app.models.soap_note import SOAPNote, SOAPSection
