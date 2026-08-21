import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.soap_note import SOAPNote, SOAPNoteStatus, SOAPSectionType, GenerationStatus
from app.models.code_suggestion import CodeSuggestion, CodeType
from app.services.code_reference_service import CodeReferenceService

from app.services.exceptions import CodeSuggestionTimeoutError, SOAPNoteAlreadySignedError

logger = logging.getLogger(__name__)

class CodeSuggesterService:
    @staticmethod
    def prepare_generation(soap_note_id: int, db: Session = None) -> None:
        """
        Sets the SOAP note's code generation status to processing.
        """
        db_session = db or SessionLocal()
        try:
            note = db_session.query(SOAPNote).filter_by(id=soap_note_id).first()
            if not note:
                raise ValueError(f"SOAPNote with id {soap_note_id} not found.")

            if note.status == SOAPNoteStatus.SIGNED:
                raise SOAPNoteAlreadySignedError("Cannot generate suggestions for a SIGNED note.")

            note.codes_generation_status = GenerationStatus.processing
            note.codes_generation_error = None
            # Not note.created_at: the doctor reads the draft before asking for
            # codes, so the note is routinely minutes old by the time this runs.
            note.codes_generation_started_at = datetime.now(timezone.utc)
            db_session.commit()
        except Exception as e:
            if not db:
                db_session.rollback()
            raise e
        finally:
            if not db:
                db_session.close()

    @staticmethod
    def generate_in_background(soap_note_id: int) -> None:
        """
        Generates and persists ranked ICD-10/CPT code suggestions for a given SOAP note.
        Only uses the ASSESSMENT and PLAN sections.
        """
        db_session = SessionLocal()
        try:
            note = db_session.query(SOAPNote).filter_by(id=soap_note_id).first()
            if not note:
                raise ValueError(f"SOAPNote with id {soap_note_id} not found.")

            if note.status == SOAPNoteStatus.SIGNED:
                raise SOAPNoteAlreadySignedError("Cannot generate suggestions for a SIGNED note.")

            # Delete existing suggestions for regeneration
            db_session.query(CodeSuggestion).filter_by(soap_note_id=soap_note_id).delete()
            
            # Extract Assessment and Plan
            assessment_text = ""
            plan_text = ""
            for section in note.sections:
                if section.section_type == SOAPSectionType.ASSESSMENT:
                    assessment_text = section.content.strip()
                elif section.section_type == SOAPSectionType.PLAN:
                    plan_text = section.content.strip()

            def is_empty(text: str) -> bool:
                return not text or text == "Not documented in dialogue."

            ref_service = CodeReferenceService.get_instance()
            matches = []

            # 1. Search ICD10 codes using Assessment
            # 2. Search CPT codes using Plan
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
            from app.core.config import settings
            from app.core.metrics import metrics

            def _run_searches():
                _matches = []
                if not is_empty(assessment_text):
                    icd10_matches = ref_service.search_codes(
                        text=assessment_text, 
                        top_k=5, 
                        code_type=CodeType.ICD10
                    )
                    _matches.extend(icd10_matches)
                if not is_empty(plan_text):
                    cpt_matches = ref_service.search_codes(
                        text=plan_text, 
                        top_k=5, 
                        code_type=CodeType.CPT
                    )
                    _matches.extend(cpt_matches)
                return _matches

            executor = ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(_run_searches)
                matches = future.result(timeout=settings.NLP_TIMEOUT_SECONDS)
                metrics.record_metric("code_suggestion", True)
            except FuturesTimeoutError as exc:
                metrics.record_metric("code_suggestion", False)
                logger.warning("CodeSuggestion inference timed out. Underlying thread continues.")
                # Not HTTPException: there is no request to return a status to
                # here, and the string ends up in codes_generation_error where
                # the client reads it. The doctor recovers via the attention
                # list, which is what CODES_GENERATION_FAILED is for.
                raise CodeSuggestionTimeoutError(
                    f"Code suggestion timed out after {settings.NLP_TIMEOUT_SECONDS}s"
                ) from exc
            except Exception:
                metrics.record_metric("code_suggestion", False)
                raise
            finally:
                executor.shutdown(wait=False)

            if not matches:
                logger.info(f"Note {soap_note_id} has empty/fallback Assessment and Plan, or yielded no matches. Skipping suggestions.")
                note.codes_generation_status = GenerationStatus.completed
                db_session.commit()
                return

            new_suggestions = []
            for rank, (ref, score) in enumerate(matches, start=1):
                suggestion = CodeSuggestion(
                    soap_note_id=soap_note_id,
                    code=ref.code,
                    description=ref.description,
                    code_type=ref.code_type,
                    rank=rank,
                    confidence_score=score,
                    accepted=False
                )
                db_session.add(suggestion)
                new_suggestions.append(suggestion)

            # Finalize status
            note.codes_generation_status = GenerationStatus.completed
            note.codes_generation_error = None
            db_session.commit()
            
        except Exception as e:
            db_session.rollback()
            logger.exception("Background Code Suggestion generation failed for note %s", soap_note_id)
            note = db_session.query(SOAPNote).filter_by(id=soap_note_id).first()
            if note:
                note.codes_generation_status = GenerationStatus.failed
                note.codes_generation_error = str(e)
                db_session.commit()
            # Deliberately not re-raised. This runs as a FastAPI BackgroundTask,
            # after the response has already been sent, so there is nowhere for
            # an exception to go except out of the ASGI call. The failure is
            # recorded on the note, which is how the client and the attention
            # list learn about it. SOAPNoteService.generate_in_background does
            # the same; these two must not disagree.
        finally:
            db_session.close()
