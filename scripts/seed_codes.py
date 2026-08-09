import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sqlalchemy.dialects.postgresql import insert
import app.db.base  # ensure base is loaded first
from app.db.session import SessionLocal
from app.models.code_reference import CodeReference, CodeType

# A small subset of common ICD-10 and CPT codes for primary care
SEED_CODES = [
    # ICD-10 (Diagnoses)
    {"code": "I10", "description": "Essential (primary) hypertension", "code_type": CodeType.ICD10},
    {"code": "E11.9", "description": "Type 2 diabetes mellitus without complications", "code_type": CodeType.ICD10},
    {"code": "J01.90", "description": "Acute sinusitis, unspecified", "code_type": CodeType.ICD10},
    {"code": "E78.5", "description": "Hyperlipidemia, unspecified", "code_type": CodeType.ICD10},
    {"code": "J02.9", "description": "Acute pharyngitis, unspecified", "code_type": CodeType.ICD10},
    {"code": "M54.5", "description": "Low back pain", "code_type": CodeType.ICD10},
    {"code": "R51.9", "description": "Headache, unspecified", "code_type": CodeType.ICD10},
    {"code": "R07.9", "description": "Chest pain, unspecified", "code_type": CodeType.ICD10},
    {"code": "J45.909", "description": "Unspecified asthma, uncomplicated", "code_type": CodeType.ICD10},
    {"code": "N39.0", "description": "Urinary tract infection, site not specified", "code_type": CodeType.ICD10},
    {"code": "K21.9", "description": "Gastro-esophageal reflux disease without esophagitis", "code_type": CodeType.ICD10},
    {"code": "F41.1", "description": "Generalized anxiety disorder", "code_type": CodeType.ICD10},
    {"code": "F32.9", "description": "Major depressive disorder, single episode, unspecified", "code_type": CodeType.ICD10},
    {"code": "L70.0", "description": "Acne vulgaris", "code_type": CodeType.ICD10},
    {"code": "M25.561", "description": "Pain in right knee", "code_type": CodeType.ICD10},
    {"code": "M25.562", "description": "Pain in left knee", "code_type": CodeType.ICD10},
    {"code": "S93.401A", "description": "Sprain of unspecified ligament of right ankle, initial encounter", "code_type": CodeType.ICD10},
    {"code": "S93.402A", "description": "Sprain of unspecified ligament of left ankle, initial encounter", "code_type": CodeType.ICD10},
    {"code": "R11.2", "description": "Nausea with vomiting, unspecified", "code_type": CodeType.ICD10},
    {"code": "R50.9", "description": "Fever, unspecified", "code_type": CodeType.ICD10},
    {"code": "J06.9", "description": "Acute upper respiratory infection, unspecified", "code_type": CodeType.ICD10},
    {"code": "J20.9", "description": "Acute bronchitis, unspecified", "code_type": CodeType.ICD10},
    
    # CPT (Procedures/Visits)
    {"code": "99213", "description": "Office or other outpatient visit for the evaluation and management of an established patient (Low complexity, 20-29 mins)", "code_type": CodeType.CPT},
    {"code": "99214", "description": "Office or other outpatient visit for the evaluation and management of an established patient (Moderate complexity, 30-39 mins)", "code_type": CodeType.CPT},
    {"code": "99215", "description": "Office or other outpatient visit for the evaluation and management of an established patient (High complexity, 40-54 mins)", "code_type": CodeType.CPT},
    {"code": "99203", "description": "Office or other outpatient visit for the evaluation and management of a new patient (Low complexity, 30-44 mins)", "code_type": CodeType.CPT},
    {"code": "99204", "description": "Office or other outpatient visit for the evaluation and management of a new patient (Moderate complexity, 45-59 mins)", "code_type": CodeType.CPT},
    {"code": "81002", "description": "Urinalysis, by dip stick or tablet reagent", "code_type": CodeType.CPT},
    {"code": "87880", "description": "Infectious agent antigen detection by immunoassay with direct optical observation; Streptococcus, group A", "code_type": CodeType.CPT},
    {"code": "93000", "description": "Electrocardiogram, routine ECG with at least 12 leads; with interpretation and report", "code_type": CodeType.CPT}
]

def seed_codes():
    db = SessionLocal()
    try:
        print(f"Seeding {len(SEED_CODES)} reference codes...")
        
        # Use PostgreSQL's ON CONFLICT DO UPDATE for idempotency
        stmt = insert(CodeReference).values(SEED_CODES)
        
        # If the code already exists, we can update the description
        stmt = stmt.on_conflict_do_update(
            index_elements=['code'],
            set_={
                'description': stmt.excluded.description,
                'code_type': stmt.excluded.code_type
            }
        )
        
        db.execute(stmt)
        db.commit()
        print("Seed completed successfully!")
        
        count = db.query(CodeReference).count()
        print(f"Total codes in database: {count}")
        
    except Exception as e:
        print(f"Error seeding codes: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_codes()
