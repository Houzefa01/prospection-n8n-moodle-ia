#!/usr/bin/env python3
"""Workflow 5 — DÉTECTION DE RÉPONSE (IMAP polling, pas de webhook).
- Lit hsavatra@gmail.com via IMAP (mot de passe d'application).
- Rapproche l'expéditeur avec les leads (contacte/relance) -> statut 'repondu'.
- Notification Telegram immédiate avec résumé (LLM si dispo, sinon extrait).
Usage:
  python3 scripts/check_replies.py [--since-days 7] [--mark-seen]
  (cron local ou Schedule Trigger n8n : toutes les 15-30 min)
"""
import argparse
import email
import email.header
import email.utils
import imaplib
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_conn, now_iso, env_bool, load_dotenv

load_dotenv()

def decode_mime(s) -> str:
    if not s:
        return ""
    parts = []
    for frag, enc in email.header.decode_header(s):
        if isinstance(frag, bytes):
            parts.append(frag.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(frag)
    return "".join(parts)

def corps_texte(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return str(msg.get_payload() or "")

def resumer(texte: str, expediteur: str, organisation: str) -> str:
    extrait = " ".join((texte or "").split())[:600]
    try:
        from personalize import appel_llm
        prompt = (f"Résume en 2-3 phrases, en français, cette réponse d'un prospect "
                  f"({expediteur}, {organisation}). Ton neutre. Texte :\n{extrait}")
        r = appel_llm(prompt)
        if r:
            return r
    except Exception:
        pass
    return f"Extrait : {extrait[:400]}" if extrait else "(message vide ou non textuel)"

def notifier_telegram(texte: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("Telegram non configuré (TELEGRAM_BOT_TOKEN/CHAT_ID vides) — notif affichée seulement :")
        print(texte)
        return False
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps({"chat_id": chat, "text": texte[:4000]}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20):
            pass
        return True
    except Exception as e:
        print(f"Telegram erreur : {e}")
        return False

def verifier(since_days: int = 7, mark_seen: bool = False, dry: bool = False) -> int:
    host = os.getenv("IMAP_HOST", "imap.gmail.com")
    user = os.getenv("IMAP_USER", "")
    pwd = os.getenv("IMAP_APP_PASSWORD", "") or os.getenv("SMTP_APP_PASSWORD", "")
    folder = os.getenv("IMAP_FOLDER", "INBOX")
    if not user or not pwd:
        print("IMAP_USER / IMAP_APP_PASSWORD manquants dans .env — vérification impossible.")
        return 0
    date_limite = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS replies_vues
                    (message_id TEXT PRIMARY KEY, lead_id INTEGER, seen_at TEXT)""")
    conn.commit()
    trouves = 0
    try:
        with imaplib.IMAP4_SSL(host, 993) as m:
            m.login(user, pwd)
            m.select(folder)
            typ, data = m.search(None, f'(SINCE {date_limite})')
            ids = data[0].split() if typ == "OK" else []
            print(f"{len(ids)} message(s) depuis le {date_limite}.")
            for num in ids:
                typ, msg_data = m.fetch(num, "(RFC822)")
                if typ != "OK":
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                from_raw = msg.get("From", "")
                _, addr = email.utils.parseaddr(from_raw)
                addr = addr.lower().strip()
                sujet = decode_mime(msg.get("Subject", ""))
                corps = corps_texte(msg)
                if not addr or addr == user.lower():
                    continue  # ignore nos propres envois
                mid = (msg.get("Message-ID") or "").strip()
                if mid and conn.execute(
                    "SELECT 1 FROM replies_vues WHERE message_id=?", (mid,)
                ).fetchone():
                    continue  # déjà traitée (évite les doubles notifs Telegram)
                lead = conn.execute(
                    "SELECT * FROM leads WHERE lower(email)=? AND statut IN ('contacte','relance','approuve')",
                    (addr,),
                ).fetchone()
                if not lead:
                    continue
                lead = dict(lead)
                resume = resumer(corps, addr, lead.get("organisation", ""))
                ts = now_iso()
                if not dry:
                    conn.execute(
                        "UPDATE leads SET statut='repondu', date_derniere_action=?, updated_at=? WHERE id=?",
                        (ts, ts, lead["id"]),
                    )
                    if mid:
                        conn.execute(
                            "INSERT OR IGNORE INTO replies_vues (message_id, lead_id, seen_at) VALUES (?,?,?)",
                            (mid, lead["id"], ts),
                        )
                    conn.commit()
                trouves += 1
                notif = (f"🎯 RÉPONSE reçue !\nLead : {lead.get('organisation')} — {lead.get('contact')} <{addr}>\n"
                         f"Objet : {sujet}\nRésumé : {resume}")
                notifier_telegram(notif)
                print(f"Lead {lead['id']} ({addr}) -> REPONDU.")
                if mark_seen and not dry:
                    m.store(num, "+FLAGS", "\\Seen")
    except imaplib.IMAP4.error as e:
        print(f"IMAP erreur : {e}")
    finally:
        conn.close()
    print(f"{trouves} réponse(s) de leads détectée(s).")
    return trouves

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-days", type=int, default=7)
    ap.add_argument("--mark-seen", action="store_true")
    ap.add_argument("--dry", action="store_true",
                    help="n'écrit rien en base (test). Défaut : met à jour les statuts.")
    a = ap.parse_args()
    verifier(a.since_days, a.mark_seen, a.dry)

if __name__ == "__main__":
    main()
