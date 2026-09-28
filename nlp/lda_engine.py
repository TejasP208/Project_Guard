import numpy as np
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation
from scipy.spatial.distance import cosine as scipy_cosine


N_TOPICS = 6


def train_lda(existing_texts_clean: list):
    count_vectorizer = CountVectorizer(min_df=1, max_df=0.90)
    count_matrix = count_vectorizer.fit_transform(existing_texts_clean)


    lda_model = LatentDirichletAllocation(
        n_components=N_TOPICS,
        random_state=42,
        max_iter=100,
        learning_method='batch'
    )

    lda_model.fit(count_matrix)

    topic_distributions = lda_model.transform(count_matrix)

    return lda_model, count_vectorizer, topic_distributions


def compute_lda_similarity(new_text_clean: str,
                            lda_model,
                            count_vectorizer,
                            existing_topic_distributions: np.ndarray) -> list:
    

    new_count = count_vectorizer.transform([new_text_clean])

    # Get topic distribution for new submission — shape (1, 6)
    new_topic_dist = lda_model.transform(new_count)[0]

    similarity_scores = []
    for existing_dist in existing_topic_distributions:
        # scipy_cosine gives DISTANCE (0 = identical, 1 = completely different)
        # We convert to SIMILARITY by doing 1 - distance
        distance = scipy_cosine(new_topic_dist, existing_dist)

        # Guard against NaN (can happen if a distribution is all zeros)
        if np.isnan(distance):
            similarity = 0.0
        else:
            similarity = 1.0 - distance

        similarity_scores.append(similarity)

    return similarity_scores


def get_topic_labels(lda_model, count_vectorizer, n_top_words: int = 8) -> list:
    feature_names = count_vectorizer.get_feature_names_out()
    topics = []
    for topic_idx, topic_weights in enumerate(lda_model.components_):
        # argsort gives indices sorted ascending; [-n:] takes the top n
        top_indices = topic_weights.argsort()[:-n_top_words - 1:-1]
        top_words   = [feature_names[i] for i in top_indices]
        topics.append({
            "topic_id"  : topic_idx,
            "top_words" : top_words,
            "label"     : f"Topic {topic_idx}: {', '.join(top_words[:4])}"
        })
    return topics
