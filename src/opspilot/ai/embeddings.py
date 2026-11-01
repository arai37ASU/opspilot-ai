"""Turn text into vectors with a small open-source model that runs locally.

FastEmbed downloads the model the first time it is used, then runs it on ONNX
Runtime. The model is loaded once, because loading takes seconds.
"""

from functools import lru_cache

import numpy as np
from fastembed import TextEmbedding

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIMENSIONS = 384
# Below this, free text has no real match. See similar_eval for how it was chosen.
MIN_TEXT_SIMILARITY = 0.72


@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    return TextEmbedding(EMBEDDING_MODEL)


def embed_texts(texts: list[str]) -> np.ndarray:
    """One unit-length row per text."""
    return np.array(list(_model().embed(texts)))
