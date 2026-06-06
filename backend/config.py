import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_APP_TITLE: str = os.getenv("OPENROUTER_APP_TITLE", "Northwind Expense Review")
OPENROUTER_HTTP_REFERER: str = os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost:8000")

EXTRACTION_MODEL: str = os.getenv("EXTRACTION_MODEL", "google/gemini-2.0-flash-001")
REASONING_MODEL: str = os.getenv("REASONING_MODEL", "google/gemini-2.0-flash-001")

POLICIES_DIR: Path = BASE_DIR / os.getenv("POLICIES_DIR", "data/policies").lstrip("./")
SUBMISSIONS_DIR: Path = BASE_DIR / os.getenv("SUBMISSIONS_DIR", "data/submissions").lstrip("./")
DB_PATH: Path = BASE_DIR / os.getenv("DB_PATH", "data/northwind.db").lstrip("./")
UPLOADS_DIR: Path = BASE_DIR / "data" / "uploads"
CHROMA_PATH: str = str(BASE_DIR / "data" / "chroma_db")

RETRIEVAL_TOP_K: int = int(os.getenv("RETRIEVAL_TOP_K", "6"))
RETRIEVAL_MIN_CONFIDENCE: float = float(os.getenv("RETRIEVAL_MIN_CONFIDENCE", "0.18"))
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
