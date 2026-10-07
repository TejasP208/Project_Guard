#!/usr/bin/env sh
set -eu
python -m pip install -r requirements.txt
python -m nltk.downloader stopwords wordnet omw-1.4
python -c 'from nlp.preprocessor import preprocess; assert preprocess("Students are building projects")'
