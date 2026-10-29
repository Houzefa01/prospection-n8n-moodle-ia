#!/usr/bin/env python3
"""Workflow 1 — SOURCING.
- Import CSV manuel (démarrage) : --csv ./data/leads_import.csv
- Apollo (optionnel si APOLLO_API_KEY) : --apollo [--limit 12]
- Hunter : enrichissement emails manquants : --enrich-hunter
Déduplique sur email, statut initial 'nouveau'. Stdlib uniquement.
Usage:
  python3 scripts/sourcing.py --csv ./data/leads_import.csv
  python3 scripts/sourcing.py --apollo --limit 12
"""
import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_conn, now_iso, env_int, load_dotenv

load_dotenv()

CIBLES = (
    "ONG educative, association culturelle, ecole, centre de formation, "
    "universite, edtech — utilisant ou envisageant Moodle"
)

def upsert_lead(conn, row: dict, source: str) -> str:
    email = (row.get("email") or "").strip().lower()
    if "@" not in email:
        return "ignore-sans-email"
    org = (row.get("organisation") or "").strip()
    if not org:
        return "ignore-sans-org"
    cur = conn.execute("SELECT id FROM leads WHERE email=?", (email,))
    if cur.fetchone():
        return "doublon"
    ts = now_iso()
    conn.execute(
        """INSERT INTO leads
           (organisation, contact, email, poste, secteur, pays, statut,
            date_derniere_action, source, created_at, updated_at)
           VALUES (?,?,?,?,?,?, 'nouveau',?,?,?,?)""",
        (
            org,
            (row.get("contact") or "").strip(),
            email,
            (row.get("poste") or "").strip(),
            (row.get("secteur") or "").strip(),
            (row.get("pays") or "").strip(),
            ts, source, ts, ts,
        ),
    )
    return "insere"


def import_csv(conn, path: Path, source: str = "csv") -> dict:
    stats = {"insere": 0, "doublon": 0, "ignore-sans-email": 0, "ignore-sans-org": 0}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            # tolère variantes d'en-têtes
            norm = {(k or "").strip().lower(): (v or "") for k, v in row.items()}
            mapped = {
                "organisation": norm.get("organisation", norm.get("organization", "")),
                "contact": norm.get("contact", norm.get("nom", norm.get("name", ""))),
                "email": norm.get("email", ""),
                "poste": norm.get("poste", norm.get("titre", norm.get("title", ""))),
                "secteur": norm.get("secteur", norm.get("secteur d'activité", norm.get("industry", ""))),
                "pays": norm.get("pays", norm.get("country", "")),
            }
            r = upsert_lead(conn, mapped, source)
            stats[r] = stats.get(r, 0) + 1
    conn.commit()
    return stats


def apollo_search(limit: int) -> list[dict]:
    """Recherche Apollo : titres e-learning / formation + mots-clés ONG/éducation."""
    key = os.getenv("APOLLO_API_KEY", "").strip()
    if not key:
        print("APOLLO_API_KEY vide — sourcing Apollo ignoré (utilisez --csv).")
        return []
    payload = {
        "page": 1,
        "per_page": min(limit, 25),
        "person_titles": ["Head of Learning", "E-learning Manager", "Training Manager",
                          "Education Program Manager", "LMS Administrator", "Directeur formation"],
        "q_keywords": "Moodle e-learning NGO education training",
    }
    req = urllib.request.Request(
        "https://api.apollo.io/api/v1/mixed_people/search",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Api-Key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"Apollo erreur : {e}")
        return []
    out = []
    for p in data.get("people", [])[:limit]:
        org = (p.get("organization") or {}).get("name", "")
        out.append({
            "organisation": org,
            "contact": p.get("name", ""),
            "email": p.get("email", ""),
            "poste": p.get("title", ""),
            "secteur": (p.get("organization") or {}).get("industry", ""),
            "pays": (p.get("organization") or {}).get("country", ""),
        })
    return out


def hunter_enrich(conn) -> int:
    """Complète les emails manquants via Hunter Email-Finder (besoin domaine)."""
    key = os.getenv("HUNTER_API_KEY", "").strip()
    if not key:
        print("HUNTER_API_KEY vide — enrichissement ignoré.")
        return 0
    rows = conn.execute(
        "SELECT id, organisation, contact FROM leads WHERE email='' OR email IS NULL LIMIT 20"
    ).fetchall()
    n = 0
    for r in rows:
        print(f"Hunter: '{r['organisation']}' sans email — recherche manuelle requise "
              f"(Hunter Email-Finder exige le domaine + nom/prénom). Lead id={r['id']} ignoré pour l'instant.")
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description="Sourcing leads")
    ap.add_argument("--csv", default=os.getenv("LEADS_CSV_PATH", "./data/leads_import.csv"))
    ap.add_argument("--no-csv", action="store_true")
    ap.add_argument("--apollo", action="store_true")
    ap.add_argument("--limit", type=int, default=env_int("WEEKLY_LEAD_TARGET", 12))
    ap.add_argument("--enrich-hunter", action="store_true")
    a = ap.parse_args()

    conn = get_conn()
    total = {}
    if not a.no_csv:
        p = Path(a.csv)
        if not p.is_absolute():
            from common import BASE_DIR
            p = BASE_DIR / p
        if p.exists():
            s = import_csv(conn, p)
            print(f"CSV {p} : {s}")
            total["csv"] = s
        else:
            print(f"CSV introuvable ({p}) — ignoré. Créez-le ou utilisez --apollo.")
    if a.apollo:
        leads = apollo_search(a.limit)
        ins = sum(1 for L in leads if upsert_lead(conn, L, "apollo") == "insere")
        conn.commit()
        print(f"Apollo : {ins} insérés / {len(leads)} retournés")
        total["apollo"] = ins
    if a.enrich_hunter:
        total["hunter"] = hunter_enrich(conn)
    n = conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
    conn.close()
    print(f"Total base : {n} leads. Cibles : {CIBLES}")


if __name__ == "__main__":
    main()
