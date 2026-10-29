#!/usr/bin/env python3
"""Workflow 4 — RELANCES J+3 / J+7 (max 2, messages différents).
- --prepare : génère les brouillons de relance (LLM ou gabarit), n'envoie rien.
- --approve <id> --num 1|2 : validation humaine du brouillon.
- --send : envoie les relances dues ET approuvées (si REQUIRE_APPROVAL=true).
  Respecte DAILY_SEND_LIMIT et DRY_RUN.
Usage:
  python3 scripts/followup.py --prepare
  python3 scripts/followup.py --approve 3 --num 1
  python3 scripts/followup.py --send
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_conn, now_iso, env_bool, env_int, load_dotenv
from send import envoyer_smtp, envois_aujourdhui, extraire_objet_corps

load_dotenv()

def ensure_cols(conn) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
    for c in ("relance1_approuve", "relance2_approuve"):
        if c not in cols:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {c} INTEGER NOT NULL DEFAULT 0")
    conn.commit()

def jours_depuis(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return 999.0

def gabarit_relance(lead: dict, num: int, lang: str) -> str:
    name = os.getenv("FREELANCER_NAME", "[TON NOM]")
    contact = lead.get("contact") or ("there" if lang == "en" else "vous")
    org = lead.get("organisation") or ("your organisation" if lang == "en" else "votre organisation")
    if lang == "fr":
        if num == 1:
            return (f"Objet : Petit suivi — {org} / Moodle\n\nBonjour {contact},\n\n"
                    f"Je me permets un court suivi de mon message de cette semaine : "
                    f"j'accompagne des organisations éducatives sur Moodle (déploiement, administration) "
                    f"et l'ajout d'IA (automatisations, assistants).\n"
                    f"Un exemple concret : 3 Moodle opérés pour des académies de musique internationales, "
                    f"plus un serveur automatisé par IA en production.\n\n"
                    f"Un appel de 20 minutes vous serait-il utile pour voir ce qui s'appliquerait chez vous ?\n\n"
                    f"Cordialement,\n{name}")
        return (f"Objet : Dernier message — ressources Moodle offertes\n\nBonjour {contact},\n\n"
                f"Je ne veux pas encombrer votre boîte : c'est mon dernier message.\n"
                f"Si la modernisation Moodle / IA devient d'actualité pour {org}, "
                f"je peux offrir un mini-audit gratuit de votre plateforme (points rapides, sans engagement).\n"
                f"Dites-moi simplement « oui » et je vous l'envoie.\n\nCordialement,\n{name}")
    if num == 1:
        return (f"Subject: Quick follow-up — {org} / Moodle\n\nHi {contact},\n\n"
                f"Just floating my note from this week to the top of your inbox: "
                f"I help education organisations run Moodle (hosting, admin) and add AI "
                f"(automations, assistants).\n"
                f"Recent work: 3 Moodle servers for international music academies, "
                f"plus one AI-automated server in production.\n\n"
                f"Would a 20-minute call help map what applies to you?\n\nBest,\n{name}")
    return (f"Subject: Closing the loop — free Moodle notes\n\nHi {contact},\n\n"
            f"I don't want to clutter your inbox, so this is my last note.\n"
            f"If Moodle/AI modernisation becomes relevant for {org}, "
            f"I can share a free mini-audit of your platform (quick wins, no strings attached).\n"
            f"Just reply “yes” and I'll send it over.\n\nBest,\n{name}")

def preparer() -> int:
    from personalize import appel_llm, langue_pour
    conn = get_conn(); ensure_cols(conn)
    rows = conn.execute(
        "SELECT * FROM leads WHERE statut IN ('contacte','relance') AND relances_envoyees < 2"
    ).fetchall()
    j1 = env_int("FOLLOWUP_DAY_1", 3); j2 = env_int("FOLLOWUP_DAY_2", 7)
    n = 0
    for r in rows:
        lead = dict(r)
        proble = jours_depuis(lead.get("date_derniere_action") or "")
        num = (lead.get("relances_envoyees") or 0) + 1
        seuil = j1 if num == 1 else j2
        if proble < seuil:
            continue
        col = f"message_relance_{num}"
        if lead.get(col):
            continue  # déjà un brouillon en attente
        lang = langue_pour(lead)
        prompt = (f"Rédige une relance n°{num} courte (80-100 mots) pour {lead.get('contact')} "
                  f"({lead.get('organisation')}). Ton courtois, sans culpabilisation. "
                  f"{'Dernière relance : proposer un mini-audit gratuit.' if num==2 else 'Rappeler la preuve Moodle+IA en 1 phrase.'} "
                  f"Langue : {'français' if lang=='fr' else 'anglais'}. Première ligne 'Objet: ...'.")
        texte = appel_llm(prompt) or gabarit_relance(lead, num, lang)
        ts = now_iso()
        conn.execute(f"UPDATE leads SET {col}=?, updated_at=? WHERE id=?", (texte, ts, lead["id"]))
        conn.commit(); n += 1
        print(f"lead {lead['id']} : brouillon relance{num} prêt (à approuver).")
    conn.close()
    print(f"{n} brouillon(s) de relance — validation humaine requise.")
    return n

def approuver(lead_id: int, num: int) -> None:
    conn = get_conn(); ensure_cols(conn)
    r = conn.execute("SELECT id, email FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not r:
        print("Lead introuvable."); return
    conn.execute(f"UPDATE leads SET relance{num}_approuve=1, updated_at=? WHERE id=?", (now_iso(), lead_id))
    conn.commit(); conn.close()
    print(f"Relance{num} du lead {lead_id} APPROUVÉE.")

def envoyer_relances(limit: int) -> int:
    require = env_bool("REQUIRE_APPROVAL", True)
    dry = env_bool("DRY_RUN", True)
    quota = min(limit, env_int("DAILY_SEND_LIMIT", 12))
    conn = get_conn(); ensure_cols(conn)
    deja = envois_aujourdhui(conn)
    restant = quota - deja
    if restant <= 0:
        print(f"Quota journalier atteint ({deja}/{quota})."); conn.close(); return 0
    j1 = env_int("FOLLOWUP_DAY_1", 3); j2 = env_int("FOLLOWUP_DAY_2", 7)
    rows = conn.execute(
        "SELECT * FROM leads WHERE statut IN ('contacte','relance') AND relances_envoyees < 2 ORDER BY id"
    ).fetchall()
    n = 0
    for r in rows:
        if n >= restant:
            break
        lead = dict(r)
        proble = jours_depuis(lead.get("date_derniere_action") or "")
        num = (lead.get("relances_envoyees") or 0) + 1
        seuil = j1 if num == 1 else j2
        if proble < seuil:
            continue
        texte = lead.get(f"message_relance_{num}") or ""
        if not texte:
            print(f"lead {lead['id']} : pas de brouillon relance{num} — lancez --prepare d'abord.")
            continue
        if require and not lead.get(f"relance{num}_approuve"):
            print(f"lead {lead['id']} : relance{num} NON approuvée — --approve {lead['id']} --num {num} requis.")
            continue
        sujet, corps = extraire_objet_corps(texte)
        if dry:
            print(f"[DRY-RUN] relance{num} -> {lead['email']} | {sujet[:60]}")
            conn.execute(
                "INSERT INTO email_log (lead_id, type_envoi, sent_at, dry_run, sujet, statut) VALUES (?,?,?,?,?,?)",
                (lead["id"], f"relance{num}", now_iso(), 1, sujet, "dry-run"),
            )
        else:
            try:
                envoyer_smtp(lead["email"], sujet, corps)
                ts = now_iso()
                conn.execute(
                    "INSERT INTO email_log (lead_id, type_envoi, sent_at, dry_run, sujet, statut) VALUES (?,?,?,?,?,?)",
                    (lead["id"], f"relance{num}", ts, 0, sujet, "envoye"),
                )
                conn.execute(
                    """UPDATE leads SET statut='relance', relances_envoyees=relances_envoyees+1,
                       date_derniere_action=?, updated_at=? WHERE id=?""",
                    (ts, ts, lead["id"]),
                )
                print(f"Relance{num} ENVOYÉE -> {lead['email']}")
                n += 1
            except Exception as e:
                print(f"ÉCHEC relance {lead['email']} : {e}")
        conn.commit()
    conn.close()
    print(f"Terminé : {n} relance(s) réelle(s). Dry-run={dry}.")
    return n

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--approve", type=int)
    ap.add_argument("--num", type=int, choices=[1, 2], default=1)
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--limit", type=int, default=env_int("DAILY_SEND_LIMIT", 12))
    a = ap.parse_args()
    if a.prepare: preparer()
    elif a.approve: approuver(a.approve, a.num)
    elif a.send: envoyer_relances(a.limit)
    else: ap.print_help()

if __name__ == "__main__":
    main()
