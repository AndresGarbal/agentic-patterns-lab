# Load .env before any module reads os.getenv at import time (app.config does).
from dotenv import load_dotenv

load_dotenv()
