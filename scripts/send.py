#!/usr/bin/env python3
"""Workflow 3 — ENVOI (SMTP Gmail, garde-fous stricts).
- N'envoie QUE les leads 'approuve' si REQUIRE_APPROVAL=true (défaut).
- Limite DAILY_SEND_LIMIT (défaut 12). Compte les envois réels du jour (email_log).
- DRY_RUN=true (défaut) : logue sans envoyer.
- LinkedIn : affichage manuel uniquement, jamais d'envoi auto.
Usage:
  python3 scripts/send.py --approve 3        # valider le brouillon (humain)
  python3 scripts/send.py --list             # brouillons à valider
  python3 scripts/send.py --send [--limit 12]
  python3 scripts/send.py --linkedin 3       # message LinkedIn à copier à la main
"""
import argparse
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_conn, now_iso, env_bool, env_int, load_dotenv

load_dotenv()

def extraire_objet_corps(texte: str) -> tuple[str, str]:
    lignes = (texte or "").strip().splitlines()
    if lignes and lignes[0].lower().startswith(("objet:", "subject:")):
        return lignes[0].split(":", 1)[1].strip(), "\n".join(lignes[1:]).strip()
    return "Votre plateforme Moodle — échange de 20 minutes ?", (texte or "").strip()

def envois_aujourdhui(conn) -> int:
    jour = now_iso()[:10]
    r = conn.execute(
        "SELECT COUNT(*) c FROM email_log WHERE substr(sent_at,1,10)=? AND dry_run=0", (jour,)
    ).fetchone()
    return r["c"]

def envoyer_smtp(destinataire: str, sujet: str, corps: str) -> None:
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = env_int("SMTP_PORT", 587)
    user = os.getenv("SMTP_USER", "")
    pwd = os.getenv("SMTP_APP_PASSWORD", "")
    if not user or not pwd:
        raise RuntimeError("SMTP_USER / SMTP_APP_PASSWORD manquants dans .env "
                           "(mot de passe d'application Gmail requis)")
    msg = EmailMessage()
    msg["From"] = f"{os.getenv('SMTP_FROM_NAME', os.getenv('FREELANCER_NAME',''))} <{user}>" if os.getenv("SMTP_FROM_NAME") or os.getenv("FREELANCER_NAME") else user
    msg["To"] = destinataire
    msg["Subject"] = sujet
    msg.set_content(corps)
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)

def approuver(lead_id: int) -> None:
    conn = get_conn()
    r = conn.execute("SELECT id, statut, email FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not r:
        print(f"Lead {lead_id} introuvable."); return
    if r["statut"] not in ("brouillon", "nouveau"):
        print(f"Lead {lead_id} statut={r['statut']} — approbation refusée."); return
    ts = now_iso()
    conn.execute("UPDATE leads SET statut='approuve', date_derniere_action=?, updated_at=? WHERE id=?",
                 (ts, ts, lead_id))
    conn.commit(); conn.close()
    print(f"Lead {lead_id} ({r['email']}) APPROUVÉ — prêt pour envoi.")

def lister() -> None:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, organisation, contact, email, statut FROM leads WHERE statut IN ('brouillon','approuve','nouveau') ORDER BY id"
    ).fetchall()
    conn.close()
    if not rows:
        print("Rien à valider.")
        return
    for r in rows:
        print(f"[{r['id']}] {r['statut']:9} {r['organisation']} — {r['contact']} <{r['email']}>")

def envoyer(limit: int) -> int:
    require = env_bool("REQUIRE_APPROVAL", True)
    dry = env_bool("DRY_RUN", True)
    quota = min(limit, env_int("DAILY_SEND_LIMIT", 12))
    conn = get_conn()
    deja = envois_aujourdhui(conn)
    restant = quota - deja
    if restant <= 0:
        print(f"Quota journalier atteint ({deja}/{quota} envoyés). Repos — limite anti-spam.")
        conn.close(); return 0
    statut_ok = "'approuve'" if require else "'approuve','brouillon'"
    rows = conn.execute(
        f"SELECT * FROM leads WHERE statut IN ({statut_ok}) AND message_genere<>'' ORDER BY id LIMIT ?",
        (restant,),
    ).fetchall()
    if not rows:
        print("Aucun lead approuvé avec brouillon à envoyer. Validez d'abord : --list puis --approve <id>.")
        conn.close(); return 0
    n = 0
    for r in rows:
        sujet, corps = extraire_objet_corps(r["message_genere"])
        if dry:
            print(f"[DRY-RUN] -> {r['email']} | {sujet[:60]}")
            conn.execute(
                "INSERT INTO email_log (lead_id, type_envoi, sent_at, dry_run, sujet, statut) VALUES (?,?,?,?,?,?)",
                (r["id"], "premier", now_iso(), 1, sujet, "dry-run"),
            )
        else:
            try:
                envoyer_smtp(r["email"], sujet, corps)
                print(f"ENVOYÉ -> {r['email']}")
                conn.execute(
                    "INSERT INTO email_log (lead_id, type_envoi, sent_at, dry_run, sujet, statut) VALUES (?,?,?,?,?,?)",
                    (r["id"], "premier", now_iso(), 0, sujet, "envoye"),
                )
                ts = now_iso()
                conn.execute(
                    "UPDATE leads SET statut='contacte', emails_envoyes=emails_envoyes+1, date_derniere_action=?, updated_at=? WHERE id=?",
                    (ts, ts, r["id"]),
                )
                n += 1
            except Exception as e:
                print(f"ÉCHEC {r['email']} : {e}")
                conn.execute(
                    "INSERT INTO email_log (lead_id, type_envoi, sent_at, dry_run, sujet, statut) VALUES (?,?,?,?,?,?)",
                    (r["id"], "premier", now_iso(), 0, sujet, f"echec: {e}"),
                )
        conn.commit()
    conn.close()
    print(f"Terminé : {n} envoi(s) réel(s). Dry-run={dry}. Quota {quota}/jour respecté.")
    return n

def afficher_linkedin(lead_id: int) -> None:
    conn = get_conn()
    r = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    conn.close()
    if not r:
        print("Lead introuvable."); return
    print("=== LinkedIn — COPIER À LA MAIN (envoi auto interdit) ===")
    print(r["linkedin_message"] or "(pas encore généré — lancez personalize.py)")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--approve", type=int)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--limit", type=int, default=env_int("DAILY_SEND_LIMIT", 12))
    ap.add_argument("--linkedin", type=int)
    a = ap.parse_args()
    if a.approve: approuver(a.approve)
    elif a.list: lister()
    elif a.send: envoyer(a.limit)
    elif a.linkedin: afficher_linkedin(a.linkedin)
    else: ap.print_help()

if __name__ == "__main__":
    main()
