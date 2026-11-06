import os

MODEL = os.environ.get("THUKY_MODEL", "claude-opus-5-5")
RECALL_API_KEY = os.environ.get("RECALL_API_KEY", "")
RECALL_REGION = os.environ.get("RECALL_REGION", "us-west-2")
RECALL_LANGUAGE = os.environ.get("RECALL_LANGUAGE", "vi")
BOT_NAME = os.environ.get("BOT_NAME", "Thư Ký AI")
DB_PATH = os.environ.get("DB_PATH", "thukyai.db")
GLOSSARY = [t.strip() for t in os.environ.get("GLOSSARY", "").split(",") if t.strip()]
