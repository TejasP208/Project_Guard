import re
import nltk
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer


nltk.download('stopwords', quiet=True)
nltk.download('wordnet',   quiet=True)
nltk.download('omw-1.4',   quiet=True)

# Build stopword set once at module load (fast lookup)
_stop_words  = set(stopwords.words('english'))
_lemmatizer  = WordNetLemmatizer()


def preprocess(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""

    # Step 1 — lowercase
    text = text.lower()

    # Step 2 — keep only letters and spaces (removes numbers, symbols, punctuation)
    text = re.sub(r'[^a-z\s]', '', text)

    # Step 3 — split into individual words
    words = text.split()

    # Step 4 + 5 — remove stopwords AND lemmatize in one pass
    cleaned = [
        _lemmatizer.lemmatize(word)
        for word in words
        if word not in _stop_words and len(word) > 1
    ]

    return " ".join(cleaned)


def preprocess_batch(texts: list) -> list:
    return [preprocess(t) for t in texts]
