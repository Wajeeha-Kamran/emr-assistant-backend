import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sqlalchemy.dialects.postgresql import insert
import app.db.base  # ensure base is loaded first
from app.db.session import SessionLocal
from app.models.code_reference import CodeReference, CodeType

# A reference subset of common ICD-10 and CPT codes for primary care.
#
# Every code and description below was verified against ICD-10-CM FY2026
# (icd10data.com) and published CPT descriptors on 21 August 2026. The office
# visit codes use the CPT 2024 wording, which replaced the old time ranges
# ("30-44 minutes") with a single threshold ("30 minutes must be met or
# exceeded") - quoting the old form would state something no longer true of
# the code set. A second pass on 21 August 2026 removed the indefinite article
# from the office visit descriptors: CPT reads "and low level of medical
# decision making", not "and a low level".
#
# This is a demonstration set, not a coding authority. The published ICD-10-CM
# release runs to roughly 70,000 codes and a real deployment would load it in
# full; a curated list is used here so the project stays self-contained.
#
# The size of this list is not cosmetic. Suggestions are produced by comparing
# the note's Assessment and Plan text against these descriptions, so the system
# can only ever return a code that appears below. With the original 22 diagnosis
# codes it had no entry for migraine or for diabetes review, and returned the
# nearest thing it held - major depressive disorder for a migraine consultation.
# Adding the right codes is therefore the first fix for poor suggestions, ahead
# of any change to the matching itself.
SEED_CODES = [
    # ------------------------------------------------------------------
    # ICD-10 - general primary care
    # ------------------------------------------------------------------
    {"code": "I10", "description": "Essential (primary) hypertension", "code_type": CodeType.ICD10},
    {"code": "R03.0", "description": "Elevated blood-pressure reading, without diagnosis of hypertension", "code_type": CodeType.ICD10},
    {"code": "E78.5", "description": "Hyperlipidemia, unspecified", "code_type": CodeType.ICD10},
    {"code": "E66.9", "description": "Obesity, unspecified", "code_type": CodeType.ICD10},
    {"code": "M54.5", "description": "Low back pain", "code_type": CodeType.ICD10},
    {"code": "R07.9", "description": "Chest pain, unspecified", "code_type": CodeType.ICD10},
    {"code": "R10.9", "description": "Unspecified abdominal pain", "code_type": CodeType.ICD10},
    {"code": "R42", "description": "Dizziness and giddiness", "code_type": CodeType.ICD10},
    {"code": "R53.83", "description": "Other fatigue", "code_type": CodeType.ICD10},
    {"code": "K59.00", "description": "Constipation, unspecified", "code_type": CodeType.ICD10},
    {"code": "K21.9", "description": "Gastro-esophageal reflux disease without esophagitis", "code_type": CodeType.ICD10},
    {"code": "F41.1", "description": "Generalized anxiety disorder", "code_type": CodeType.ICD10},
    {"code": "F32.9", "description": "Major depressive disorder, single episode, unspecified", "code_type": CodeType.ICD10},
    {"code": "L70.0", "description": "Acne vulgaris", "code_type": CodeType.ICD10},
    {"code": "Z00.00", "description": "Encounter for general adult medical examination without abnormal findings", "code_type": CodeType.ICD10},

    # ------------------------------------------------------------------
    # ICD-10 - headache and migraine
    # ------------------------------------------------------------------
    {"code": "R51.9", "description": "Headache, unspecified", "code_type": CodeType.ICD10},
    {"code": "G43.909", "description": "Migraine, unspecified, not intractable, without status migrainosus", "code_type": CodeType.ICD10},
    {"code": "G43.109", "description": "Migraine with aura, not intractable, without status migrainosus", "code_type": CodeType.ICD10},
    {"code": "G43.009", "description": "Migraine without aura, not intractable, without status migrainosus", "code_type": CodeType.ICD10},
    {"code": "H53.19", "description": "Other subjective visual disturbances", "code_type": CodeType.ICD10},
    {"code": "R11.2", "description": "Nausea with vomiting, unspecified", "code_type": CodeType.ICD10},

    # ------------------------------------------------------------------
    # ICD-10 - throat, ear, nose, chest
    # ------------------------------------------------------------------
    {"code": "J02.9", "description": "Acute pharyngitis, unspecified", "code_type": CodeType.ICD10},
    {"code": "J02.0", "description": "Streptococcal pharyngitis", "code_type": CodeType.ICD10},
    {"code": "J03.00", "description": "Acute streptococcal tonsillitis, unspecified", "code_type": CodeType.ICD10},
    {"code": "J03.90", "description": "Acute tonsillitis, unspecified", "code_type": CodeType.ICD10},
    {"code": "R59.0", "description": "Localized enlarged lymph nodes", "code_type": CodeType.ICD10},
    {"code": "J00", "description": "Acute nasopharyngitis [common cold]", "code_type": CodeType.ICD10},
    {"code": "J01.90", "description": "Acute sinusitis, unspecified", "code_type": CodeType.ICD10},
    {"code": "J06.9", "description": "Acute upper respiratory infection, unspecified", "code_type": CodeType.ICD10},
    {"code": "J20.9", "description": "Acute bronchitis, unspecified", "code_type": CodeType.ICD10},
    {"code": "J45.909", "description": "Unspecified asthma, uncomplicated", "code_type": CodeType.ICD10},
    {"code": "B34.9", "description": "Viral infection, unspecified", "code_type": CodeType.ICD10},
    {"code": "R50.9", "description": "Fever, unspecified", "code_type": CodeType.ICD10},

    # ------------------------------------------------------------------
    # ICD-10 - diabetes and its complications
    # ------------------------------------------------------------------
    {"code": "E11.9", "description": "Type 2 diabetes mellitus without complications", "code_type": CodeType.ICD10},
    {"code": "E11.65", "description": "Type 2 diabetes mellitus with hyperglycemia", "code_type": CodeType.ICD10},
    {"code": "E11.40", "description": "Type 2 diabetes mellitus with diabetic neuropathy, unspecified", "code_type": CodeType.ICD10},
    {"code": "E11.42", "description": "Type 2 diabetes mellitus with diabetic polyneuropathy", "code_type": CodeType.ICD10},
    {"code": "E11.319", "description": "Type 2 diabetes mellitus with unspecified diabetic retinopathy without macular edema", "code_type": CodeType.ICD10},
    {"code": "R20.2", "description": "Paresthesia of skin", "code_type": CodeType.ICD10},
    {"code": "Z13.5", "description": "Encounter for screening for eye and ear disorders", "code_type": CodeType.ICD10},

    # ------------------------------------------------------------------
    # ICD-10 - musculoskeletal and injury
    # ------------------------------------------------------------------
    {"code": "S93.401A", "description": "Sprain of unspecified ligament of right ankle, initial encounter", "code_type": CodeType.ICD10},
    {"code": "S93.402A", "description": "Sprain of unspecified ligament of left ankle, initial encounter", "code_type": CodeType.ICD10},
    {"code": "M25.571", "description": "Pain in right ankle and joints of right foot", "code_type": CodeType.ICD10},
    {"code": "M25.572", "description": "Pain in left ankle and joints of left foot", "code_type": CodeType.ICD10},
    {"code": "M25.561", "description": "Pain in right knee", "code_type": CodeType.ICD10},
    {"code": "M25.562", "description": "Pain in left knee", "code_type": CodeType.ICD10},
    {"code": "M79.671", "description": "Pain in right foot", "code_type": CodeType.ICD10},
    {"code": "M79.672", "description": "Pain in left foot", "code_type": CodeType.ICD10},

    # ------------------------------------------------------------------
    # ICD-10 - urinary
    # ------------------------------------------------------------------
    {"code": "N39.0", "description": "Urinary tract infection, site not specified", "code_type": CodeType.ICD10},

    # ------------------------------------------------------------------
    # CPT - office visits
    # ------------------------------------------------------------------
    {"code": "99212", "description": "Office or other outpatient visit for the evaluation and management of an established patient, which requires a medically appropriate history and/or examination and straightforward medical decision making. When using total time on the date of the encounter for code selection, 10 minutes must be met or exceeded.", "code_type": CodeType.CPT},
    {"code": "99213", "description": "Office or other outpatient visit for the evaluation and management of an established patient, which requires a medically appropriate history and/or examination and low level of medical decision making. When using total time on the date of the encounter for code selection, 20 minutes must be met or exceeded.", "code_type": CodeType.CPT},
    {"code": "99214", "description": "Office or other outpatient visit for the evaluation and management of an established patient, which requires a medically appropriate history and/or examination and moderate level of medical decision making. When using total time on the date of the encounter for code selection, 30 minutes must be met or exceeded.", "code_type": CodeType.CPT},
    {"code": "99215", "description": "Office or other outpatient visit for the evaluation and management of an established patient, which requires a medically appropriate history and/or examination and high level of medical decision making. When using total time on the date of the encounter for code selection, 40 minutes must be met or exceeded.", "code_type": CodeType.CPT},
    {"code": "99203", "description": "Office or other outpatient visit for the evaluation and management of a new patient, which requires a medically appropriate history and/or examination and low level of medical decision making. When using total time on the date of the encounter for code selection, 30 minutes must be met or exceeded.", "code_type": CodeType.CPT},
    {"code": "99204", "description": "Office or other outpatient visit for the evaluation and management of a new patient, which requires a medically appropriate history and/or examination and moderate level of medical decision making. When using total time on the date of the encounter for code selection, 45 minutes must be met or exceeded.", "code_type": CodeType.CPT},
    {"code": "99396", "description": "Periodic comprehensive preventive medicine reevaluation and management of an individual including an age and gender appropriate history, examination, counseling/anticipatory guidance/risk factor reduction interventions, and the ordering of laboratory/diagnostic procedures, established patient; 40-64 years", "code_type": CodeType.CPT},

    # ------------------------------------------------------------------
    # CPT - laboratory
    # ------------------------------------------------------------------
    {"code": "36415", "description": "Collection of venous blood by venipuncture", "code_type": CodeType.CPT},
    {"code": "80053", "description": "Comprehensive metabolic panel", "code_type": CodeType.CPT},
    {"code": "80061", "description": "Lipid panel", "code_type": CodeType.CPT},
    {"code": "83036", "description": "Hemoglobin; glycosylated (A1C)", "code_type": CodeType.CPT},
    {"code": "82947", "description": "Glucose; quantitative, blood (except reagent strip)", "code_type": CodeType.CPT},
    {"code": "84443", "description": "Thyroid stimulating hormone (TSH)", "code_type": CodeType.CPT},
    {"code": "85025", "description": "Blood count; complete (CBC), automated (Hgb, Hct, RBC, WBC and platelet count) and automated differential WBC count", "code_type": CodeType.CPT},
    {"code": "81002", "description": "Urinalysis, by dip stick or tablet reagent for bilirubin, glucose, hemoglobin, ketones, leukocytes, nitrite, pH, protein, specific gravity, urobilinogen, any number of these constituents; non-automated, without microscopy", "code_type": CodeType.CPT},
    {"code": "87880", "description": "Infectious agent antigen detection by immunoassay with direct optical observation; Streptococcus, group A", "code_type": CodeType.CPT},

    # ------------------------------------------------------------------
    # CPT - imaging and diagnostics
    # ------------------------------------------------------------------
    {"code": "93000", "description": "Electrocardiogram, routine ECG with at least 12 leads; with interpretation and report", "code_type": CodeType.CPT},
    {"code": "71046", "description": "Radiologic examination, chest; 2 views", "code_type": CodeType.CPT},
    {"code": "73600", "description": "Radiologic examination, ankle; 2 views", "code_type": CodeType.CPT},
    {"code": "73630", "description": "Radiologic examination, foot; complete, minimum of 3 views", "code_type": CodeType.CPT},
    {"code": "92250", "description": "Fundus photography with interpretation and report", "code_type": CodeType.CPT},
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
