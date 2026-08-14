import logging
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.soap_note import SOAPNote, SOAPNoteStatus, SOAPSectionType
from app.models.code_suggestion import CodeSuggestion, CodeType
from app.services.code_reference_service import CodeReferenceService

from app.services.exceptions import SOAPNoteAlreadySignedError

logger = logging.getLogger(__name__)

class CodeSuggesterService:
    @staticmethod
    def generate_suggestions(soap_note_id: int, db: Session = None) -> list[CodeSuggestion]:
        """
        Generates and persists ranked ICD-10/CPT code suggestions for a given SOAP note.
        Only uses the ASSESSMENT and PLAN sections.
        """
        db_session = db or SessionLocal()
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
            from fastapi import HTTPException
            
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

            try:
                executor = ThreadPoolExecutor(max_workers=1)
                try:
                    future = executor.submit(_run_searches)
                    matches = future.result(timeout=settings.NLP_TIMEOUT_SECONDS)
                    metrics.record_metric("code_suggestion", True)
                except FuturesTimeoutError:
                    metrics.record_metric("code_suggestion", False)
                    logger.warning("CodeSuggestion inference timed out. Underlying thread continues.")
                    raise HTTPException(
                        status_code=503, 
                        detail="NLP Engine Timeout", 
                        headers={"Retry-After": "5"}
                    )
                finally:
                    executor.shutdown(wait=False)
            except Exception as e:
                from fastapi import HTTPException
                if isinstance(e, HTTPException):
                    raise
                metrics.record_metric("code_suggestion", False)
                raise e

            if not matches:
                logger.info(f"Note {soap_note_id} has empty/fallback Assessment and Plan, or yielded no matches. Skipping suggestions.")
                db_session.commit()
                return []

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

            db_session.commit()
            
            # Refresh to get IDs
            for s in new_suggestions:
                db_session.refresh(s)
                
            return new_suggestions

        except Exception as e:
            if not db:
                db_session.rollback()
            raise e
        finally:
            if not db:
                db_session.close()
