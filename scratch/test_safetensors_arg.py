import os
os.environ['HF_HUB_VERBOSITY'] = 'debug'
os.environ['TRANSFORMERS_NO_ADVISORY_WARNINGS'] = '1'
import logging
logging.basicConfig(level=logging.DEBUG)
from transformers import AutoModel
print('WITH ARGS')
AutoModel.from_pretrained('emilyalsentzer/Bio_ClinicalBERT', revision='d5892b39a4adaed74b92212a44081509db72f87b', use_safetensors=False)
