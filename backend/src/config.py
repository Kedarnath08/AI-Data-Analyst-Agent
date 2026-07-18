import os
from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else v


class Settings:
    # --- Google / Gemini (shared) ---
    GOOGLE_API_KEY = _get("GOOGLE_API_KEY")
    # One generation model serves both the RAG answerer and the analyst agent's
    # function-calling loop. gemini-flash-latest handles both.
    GEN_MODEL = _get("GEN_MODEL", "gemini-flash-latest")
    EMBED_MODEL = _get("EMBED_MODEL", "gemini-embedding-001")

    # --- RAG knobs ---
    TOP_K = int(_get("TOP_K", "8"))
    SIM_THRESHOLD = float(_get("SIM_THRESHOLD", "0.5"))
    CHUNK_SIZE = int(_get("CHUNK_SIZE", "1200"))
    CHUNK_OVERLAP = int(_get("CHUNK_OVERLAP", "200"))

    # --- Pinecone ---
    PINECONE_API_KEY = _get("PINECONE_API_KEY")
    PINECONE_INDEX = _get("PINECONE_INDEX", "rag-gemini-demo")
    PINECONE_CLOUD = _get("PINECONE_CLOUD", "aws")
    PINECONE_REGION = _get("PINECONE_REGION", "us-east-1")

    # --- Data analyst agent knobs ---
    MAX_AGENT_ITERATIONS = int(_get("MAX_AGENT_ITERATIONS", "8"))
    SQL_ROW_LIMIT = int(_get("SQL_ROW_LIMIT", "200"))
    PY_TIMEOUT_SECONDS = int(_get("PY_TIMEOUT_SECONDS", "20"))
    PY_MAX_OUTPUT_CHARS = int(_get("PY_MAX_OUTPUT_CHARS", "20000"))
    MAX_UPLOAD_MB = int(_get("MAX_UPLOAD_MB", "50"))


settings = Settings()
