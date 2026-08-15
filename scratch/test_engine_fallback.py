import os
os.environ['HF_HUB_VERBOSITY'] = 'debug'
import logging
logging.basicConfig(level=logging.DEBUG)
from app.ml.clinicalbert_engine import ClinicalBERTEngine

print('LOADING ENGINE')
engine = ClinicalBERTEngine.get_instance()
print('EMBEDDING')
engine.embed("test")
print('DONE')
