from huggingface_hub import HfApi
import sys

try:
    api = HfApi()
    biogpt_sha = api.model_info("microsoft/biogpt").sha
    clinicalbert_sha = api.model_info("emilyalsentzer/Bio_ClinicalBERT").sha
    print(f"BIOGPT_SHA={biogpt_sha}")
    print(f"CLINICALBERT_SHA={clinicalbert_sha}")
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
