import os
os.environ['HF_HUB_VERBOSITY'] = 'debug'
import logging
logging.basicConfig(level=logging.DEBUG)
from transformers import AutoModel
print('NO ARGS')
AutoModel.from_pretrained('emilyalsentzer/Bio_ClinicalBERT', revision='d5892b39a4adaed74b92212a44081509db72f87b')
