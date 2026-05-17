import glob
import json
import logging
import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# protobuf hack for chroma on some setups
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
load_dotenv(override=False)

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.document_compressors import FlashrankRerank
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_classic.retrievers.contextual_compression import (
    ContextualCompressionRetriever,
)
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sklearn.feature_extraction.text import HashingVectorizer
from flashrank import Ranker, RerankRequest
import langchain_community.document_compressors.flashrank_rerank as flashrank_rerank_module

if not hasattr(flashrank_rerank_module, "RerankRequest"):
    flashrank_rerank_module.RerankRequest = RerankRequest
if not hasattr(flashrank_rerank_module, "Ranker"):
    flashrank_rerank_module.Ranker = Ranker

log = logging.getLogger("KnowledgeTool")

KNOWLEDGE_DIR = os.getenv("KNOWLEDGE_BASE_DIR", "knowledge-base")
DB_NAME = os.getenv("KNOWLEDGE_VECTOR_DB_NAME", "knowledge_chroma_db")

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
LOCAL_EMBEDDING_MODEL = "local-hash-embeddings-v1"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
INDEX_VERSION = 1
MANIFEST_FILE = "manifest.json"
VECTOR_K = int(os.getenv("KNOWLEDGE_VECTOR_K", "12"))
BM25_K = int(os.getenv("KNOWLEDGE_BM25_K", "12"))
RERANK_TOP_N = int(os.getenv("KNOWLEDGE_RERANK_TOP_N", "5"))


def get_manifest_path(db_path: Path) -> Path:
    return db_path / MANIFEST_FILE


def load_manifest(db_path: Path) -> dict[str, Any] | None:
    manifest_path = get_manifest_path(db_path)
    if not manifest_path.exists():
        return None

    try:
        with manifest_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        log.warning("Could not read knowledge manifest, rebuilding index.")
        return None


def save_manifest(db_path: Path, embedding_name: str, source_state: list[dict[str, Any]]) -> None:
    manifest = {
        "index_version": INDEX_VERSION,
        "embedding_model": embedding_name,
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "source_state": source_state,
    }
    with get_manifest_path(db_path).open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)


def manifest_matches(
    manifest: dict[str, Any] | None,
    embedding_name: str,
    source_state: list[dict[str, Any]],
) -> bool:
    if not manifest:
        return False
    return (
        manifest.get("index_version") == INDEX_VERSION
        and manifest.get("embedding_model") == embedding_name
        and manifest.get("chunk_size") == CHUNK_SIZE
        and manifest.get("chunk_overlap") == CHUNK_OVERLAP
        and manifest.get("source_state") == source_state
    )


def supported_file_paths(base: Path) -> list[Path]:
    patterns = ("**/*.pdf", "**/*.md", "**/*.txt")
    files: list[Path] = []
    for pattern in patterns:
        for file_path in base.glob(pattern):
            if file_path.is_file():
                files.append(file_path)
    return sorted(files)


def get_source_state() -> list[dict[str, Any]]:
    base = Path(KNOWLEDGE_DIR)
    if not base.exists():
        return []

    state: list[dict[str, Any]] = []
    for file_path in supported_file_paths(base):
        stat = file_path.stat()
        state.append(
            {
                "path": str(file_path.relative_to(base)),
                "size": int(stat.st_size),
                "mtime": int(stat.st_mtime),
            }
        )
    return state


class LocalHashEmbeddings:
    """Embeddings without hitting the network."""

    def __init__(self, n_features: int = 1024):
        self.vectorizer = HashingVectorizer(
            n_features=n_features,
            alternate_sign=False,
            norm="l2",
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.vectorizer.transform(texts).toarray().tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.vectorizer.transform([text]).toarray()[0].tolist()


def get_embeddings():
    backend = os.getenv("KNOWLEDGE_EMBEDDING_BACKEND", "local").lower()

    if backend in ("auto", "huggingface"):
        try:
            embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
            return EMBEDDING_MODEL, embeddings
        except Exception as exc:
            if backend == "huggingface":
                raise RuntimeError(
                    "Failed to initialize HuggingFace embeddings."
                ) from exc
            log.warning("HuggingFace embeddings unavailable, trying OpenAI: %s", exc)

    if backend in ("auto", "openai"):
        try:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY is missing.")
            embeddings = OpenAIEmbeddings(
                model=OPENAI_EMBEDDING_MODEL,
                api_key=api_key,
            )
            return OPENAI_EMBEDDING_MODEL, embeddings
        except Exception as exc:
            if backend == "openai":
                raise RuntimeError("Failed to initialize OpenAI embeddings.") from exc
            log.warning("OpenAI embeddings unavailable, using local fallback: %s", exc)

    return LOCAL_EMBEDDING_MODEL, LocalHashEmbeddings()


def load_documents() -> list:
    base = Path(KNOWLEDGE_DIR)
    if not base.exists():
        return []

    documents = []

    for pdf_path in glob.glob(str(base / "**" / "*.pdf"), recursive=True):
        loader = PyPDFLoader(file_path=pdf_path)
        for doc in loader.load():
            doc.metadata["doc_type"] = "pdf"
            doc.metadata["source"] = pdf_path
            documents.append(doc)

    for pattern in ("*.md", "*.txt"):
        for text_path in glob.glob(str(base / "**" / pattern), recursive=True):
            loader = TextLoader(text_path, encoding="utf-8")
            for doc in loader.load():
                doc.metadata["doc_type"] = "text"
                doc.metadata["source"] = text_path
                documents.append(doc)

    return documents


def get_chunked_documents() -> list:
    docs = load_documents()
    if not docs:
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    return splitter.split_documents(docs)


def build_vectorstore(force_rebuild: bool = False) -> Chroma:
    rebuild_flag = os.getenv("REBUILD_KNOWLEDGE_VECTOR_DB", "false").lower() == "true"
    rebuild = force_rebuild or rebuild_flag

    db_path = Path(DB_NAME)
    temp_path = db_path.with_name(f"{db_path.name}.tmp")
    backup_path = db_path.with_name(f"{db_path.name}.bak")

    embedding_name, embeddings = get_embeddings()
    source_state = get_source_state()
    current_manifest = load_manifest(db_path)

    if db_path.exists() and not rebuild and manifest_matches(current_manifest, embedding_name, source_state):
        log.info("Using existing knowledge DB at %s", db_path)
        return Chroma(
            persist_directory=str(db_path),
            embedding_function=embeddings,
        )

    if temp_path.exists():
        shutil.rmtree(temp_path, ignore_errors=True)

    chunks = get_chunked_documents()
    if not chunks:
        raise ValueError(
            "No documents found in knowledge base. Add files under "
            f"'{KNOWLEDGE_DIR}' and rebuild."
        )

    log.info("Loaded %d knowledge chunks", len(chunks))

    try:
        Chroma.from_documents(
            documents=chunks,
            embedding=embeddings,
            persist_directory=str(temp_path),
        )
        save_manifest(temp_path, embedding_name, source_state)

        if backup_path.exists():
            shutil.rmtree(backup_path, ignore_errors=True)
        if db_path.exists():
            db_path.rename(backup_path)

        temp_path.rename(db_path)

        if backup_path.exists():
            shutil.rmtree(backup_path, ignore_errors=True)

        log.info("Knowledge vector DB built at %s", db_path)
        return Chroma(
            persist_directory=str(db_path),
            embedding_function=embeddings,
        )
    except Exception:
        if temp_path.exists():
            shutil.rmtree(temp_path, ignore_errors=True)
        if backup_path.exists() and not db_path.exists():
            backup_path.rename(db_path)
        log.exception("Failed building knowledge vector DB")
        raise


def ensure_knowledge_index_up_to_date() -> None:
    """Rebuild index if knowledge-base files changed."""
    db_path = Path(DB_NAME)
    embedding_name, _ = get_embeddings()
    manifest = load_manifest(db_path)
    current_state = get_source_state()

    if not db_path.exists() or not manifest_matches(manifest, embedding_name, current_state):
        clear_retriever_cache()
        build_vectorstore(force_rebuild=True)
        clear_retriever_cache()


@lru_cache(maxsize=1)
def get_knowledge_retriever():
    vectorstore = build_vectorstore()
    vector_retriever = vectorstore.as_retriever(search_kwargs={"k": VECTOR_K})

    chunked_docs = get_chunked_documents()
    if not chunked_docs:
        raise ValueError("No chunked documents available for BM25 retriever.")

    bm25_retriever = BM25Retriever.from_documents(chunked_docs)
    bm25_retriever.k = BM25_K

    hybrid_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, vector_retriever],
        weights=[0.5, 0.5],
    )

    try:
        compressor = FlashrankRerank(client=Ranker(), top_n=RERANK_TOP_N)
        return ContextualCompressionRetriever(
            base_compressor=compressor,
            base_retriever=hybrid_retriever,
        )
    except Exception as exc:
        log.warning(
            "FlashRank reranker unavailable, using hybrid retriever without reranking: %s",
            exc,
        )
        return hybrid_retriever


def clear_retriever_cache() -> None:
    get_knowledge_retriever.cache_clear()


def rebuild_knowledge_index() -> str:
    clear_retriever_cache()
    build_vectorstore(force_rebuild=True)
    clear_retriever_cache()
    return f"Knowledge vector DB rebuilt from '{KNOWLEDGE_DIR}'."


def query_knowledge_base(query: str) -> str:
    ensure_knowledge_index_up_to_date()
    retriever = get_knowledge_retriever()
    docs = retriever.invoke(query)

    if not docs:
        return (
            "I could not find relevant instructions in your knowledge base. "
            "Please add or update files in the knowledge-base folder."
        )

    chunks = []
    for idx, doc in enumerate(docs, start=1):
        source = Path(doc.metadata.get("source", "unknown")).name
        content = (doc.page_content or "").strip()
        if not content:
            continue
        chunks.append(f"[Source {idx}: {source}]\n{content}")

    if not chunks:
        return "I found files, but they contained no readable text."

    return "\n\n".join(chunks)
