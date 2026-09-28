from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine


def compute_tfidf_similarity(new_text_clean: str,existing_texts_clean: list) -> list:
    

    # Put new text at the end so we can easily grab it as the last row
    all_texts = existing_texts_clean + [new_text_clean]


    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=1,
        max_df=0.95,
        sublinear_tf=True
    )

    # fit_transform: learns vocabulary + IDF, then converts every text to a vector
    tfidf_matrix = vectorizer.fit_transform(all_texts)

    # Last row = new submission vector
    new_vector = tfidf_matrix[-1]

    # All rows except last = existing 66 project vectors
    existing_matrix = tfidf_matrix[:-1]

    # cosine_similarity returns shape (1, 66) — we flatten to a plain list
    scores = sklearn_cosine(new_vector, existing_matrix)[0]

    return scores.tolist()
