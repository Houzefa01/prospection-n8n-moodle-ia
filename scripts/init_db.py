#!/usr/bin/env python3
"""Init base leads (idempotent). Usage: python3 scripts/init_db.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_conn, get_db_path

conn = get_conn()
n = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
conn.close()
print(f"OK base prête : {get_db_path()} ({n} leads)")
