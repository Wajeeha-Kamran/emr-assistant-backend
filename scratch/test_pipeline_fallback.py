import os
os.environ['HF_HUB_VERBOSITY'] = 'debug'
import logging
logging.basicConfig(level=logging.DEBUG)
from transformers import AutoTokenizer, AutoModel, pipeline

print('LOADING TOKENIZER')
tokenizer = AutoTokenizer.from_pretrained('emilyalsentzer/Bio_ClinicalBERT', revision='d5892b39a4adaed74b92212a44081509db72f87b', use_safetensors=False)
print('LOADING MODEL')
model = AutoModel.from_pretrained('emilyalsentzer/Bio_ClinicalBERT', revision='d5892b39a4adaed74b92212a44081509db72f87b', use_safetensors=False)
print('LOADING PIPELINE')
pipe = pipeline('feature-extraction', model=model, tokenizer=tokenizer)
print('DONE')
