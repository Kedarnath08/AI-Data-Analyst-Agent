import os
from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else v


class Settings:
    # Google / Gemini
    GOOGLE_API_KEY = _get("GOOGLE_API_KEY")
    GEN_MODEL = _get("GEN_MODEL", "gemini-3-flash-preview")

    # Agent knobs
    MAX_AGENT_ITERATIONS = int(_get("MAX_AGENT_ITERATIONS", "8"))
    SQL_ROW_LIMIT = int(_get("SQL_ROW_LIMIT", "200"))
    PY_TIMEOUT_SECONDS = int(_get("PY_TIMEOUT_SECONDS", "20"))
    PY_MAX_OUTPUT_CHARS = int(_get("PY_MAX_OUTPUT_CHARS", "20000"))
    MAX_UPLOAD_MB = int(_get("MAX_UPLOAD_MB", "50"))


settings = Settings()
