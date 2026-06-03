import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "Nosted_data"
DB_PATH = BASE_DIR / "database" / "superdatabase.db"
PROMPTS_DIR = BASE_DIR / "prompts"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
EXTRACTION_MODEL = "claude-sonnet-4-6"
MAX_IMAGE_DPI = 150
BATCH_SIZE = 3  # pages per Claude call for large PDFs

