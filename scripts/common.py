"""Utilitaires partagés — prospection freelance Moodle + IA.
Stdlib uniquement. Chemins via env (migrable VPS), jamais codés en dur.
"""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Mini chargeur .env (sans dépendance) ---
def load_dotenv(path: Path | None = None) -> None:
    p = path or (BASE_DIR / ".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)

load_dotenv()

STATUTS = ["nouveau", "brouillon", "approuve", "contacte", "relance", "repondu", "converti", "perdu"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organisation TEXT NOT NULL,
    contact TEXT DEFAULT '',
    email TEXT NOT NULL UNIQUE,
    poste TEXT DEFAULT '',
    secteur TEXT DEFAULT '',
    pays TEXT DEFAULT '',
    statut TEXT NOT NULL DEFAULT 'nouveau'
        CHECK (statut IN ('nouveau','brouillon','approuve','contacte','relance','repondu','converti','perdu')),
    date_derniere_action TEXT DEFAULT '',
    message_genere TEXT DEFAULT '',
    message_relance_1 TEXT DEFAULT '',
    message_relance_2 TEXT DEFAULT '',
    linkedin_message TEXT DEFAULT '',
    relances_envoyees INTEGER NOT NULL DEFAULT 0,
    emails_envoyes INTEGER NOT NULL DEFAULT 0,
    source TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS email_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL REFERENCES leads(id),
    type_envoi TEXT NOT NULL DEFAULT 'premier',
    sent_at TEXT NOT NULL DEFAULT '',
    dry_run INTEGER NOT NULL DEFAULT 1,
    sujet TEXT DEFAULT '',
    statut TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_leads_statut ON leads(statut);
CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
CREATE INDEX IF NOT EXISTS idx_log_sent_at ON email_log(sent_at);
"""

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def get_db_path() -> Path:
    raw = os.getenv("LEADS_DB_PATH", "./data/leads.db")
    p = Path(raw)
    if not p.is_absolute():
        p = BASE_DIR / p
    return p

def get_conn() -> sqlite3.Connection:
    db = get_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn

def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "y", "on")

def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default
