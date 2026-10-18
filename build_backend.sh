#!/usr/bin/env sh
set -eu
python -m pip install -r requirements.txt
python -m pip check
python -m nltk.downloader -d "${NLTK_DATA:-$HOME/nltk_data}" stopwords wordnet omw-1.4
python -c 'from nlp.preprocessor import preprocess; assert preprocess("Students are building projects")'
python -c 'import main'
