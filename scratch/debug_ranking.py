import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.services.code_reference_service import CodeReferenceService
from app.models.code_reference import CodeType

def run():
    db = SessionLocal()
    try:
        assessment_text = "Patient presents with acute severe headache, likely tension-type or early migraine. Elevated blood pressure noted, possibly secondary to pain."
        results = CodeReferenceService.get_instance().search_codes(assessment_text, top_k=22, code_type=CodeType.ICD10)
        
        print(f"Total ICD10 codes searched: {len(results)}")
        for rank, (code, score) in enumerate(results, start=1):
            if code.code in ['R51.9', 'I10']:
                print(f"Rank: {rank} | Code: {code.code} | Confidence: {score:.4f} | Desc: {code.description}")
            
    finally:
        db.close()

if __name__ == "__main__":
    run()
