"""Local FAQ knowledge base, queried mid-call as a tool.

Uses LlamaIndex with a locally-run HuggingFace embedding model (no API key,
$0 cost -- the tradeoff is a one-time ~130MB model download on first run,
and slightly higher cold-start latency than an API embedding call).

We deliberately use `.as_retriever()` rather than `.as_query_engine()`: we
want the raw matched FAQ text back, not an LLM-synthesized answer, so this
module has no dependency on `app.tools.llm` and stays cheap/fast.
"""

import re
import threading
from pathlib import Path

from llama_index.core import Document, Settings, VectorStoreIndex

from app.tools.schemas import FaqAnswer

FAQ_DATA_PATH = Path(__file__).parent / "faq_data" / "faq.md"
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

# Below this cosine-similarity score, treat the FAQ as "no confident answer"
# so the graph can fall back to escalation instead of guessing.
MIN_RELEVANCE_SCORE = 0.45

_index: VectorStoreIndex | None = None
_index_lock = threading.Lock()


def _parse_faq_markdown(path: Path) -> list[Document]:
    """Split faq.md into one Document per `## heading` section."""
    text = path.read_text(encoding="utf-8")
    sections = re.split(r"^## ", text, flags=re.MULTILINE)[1:]  # drop the H1 title
    documents = []
    for section in sections:
        heading, _, body = section.partition("\n")
        documents.append(
            Document(
                text=f"{heading.strip()}\n{body.strip()}",
                metadata={"question": heading.strip()},
            )
        )
    return documents


def _get_index() -> VectorStoreIndex:
    """Build (once) and cache the in-memory vector index."""
    global _index
    if _index is not None:
        return _index

    with _index_lock:
        if _index is None:
            from llama_index.embeddings.huggingface import HuggingFaceEmbedding

            Settings.embed_model = HuggingFaceEmbedding(model_name=EMBEDDING_MODEL_NAME)
            _index = VectorStoreIndex.from_documents(_parse_faq_markdown(FAQ_DATA_PATH))
    return _index


def query_faq(question: str, top_k: int = 1) -> FaqAnswer | None:
    """Return the best-matching FAQ entry for `question`, or None if nothing
    clears MIN_RELEVANCE_SCORE (caller should escalate rather than guess).
    """
    retriever = _get_index().as_retriever(similarity_top_k=top_k)
    nodes = retriever.retrieve(question)
    if not nodes:
        return None

    best = nodes[0]
    if best.score is not None and best.score < MIN_RELEVANCE_SCORE:
        return None

    return FaqAnswer(
        answer=best.node.get_content(),
        source_question=best.node.metadata.get("question", ""),
        score=best.score or 0.0,
    )


def reload_index() -> None:
    """Force a rebuild on next `query_faq` call (e.g. after editing faq.md)."""
    global _index
    with _index_lock:
        _index = None
