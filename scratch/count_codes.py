import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.models.code_reference import CodeReference
from app.models.code_reference import CodeType

def run():
    db = SessionLocal()
    try:
        icd10_count = db.query(CodeReference).filter(CodeReference.code_type == CodeType.ICD10).count()
        cpt_count = db.query(CodeReference).filter(CodeReference.code_type == CodeType.CPT).count()
        
        print(f"ICD10 Count: {icd10_count}")
        print(f"CPT Count: {cpt_count}")
    finally:
        db.close()

if __name__ == "__main__":
    run()
