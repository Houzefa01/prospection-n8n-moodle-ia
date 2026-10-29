#!/usr/bin/env python3
"""Workflow 2 — PERSONNALISATION IA.
Pour chaque lead 'nouveau' : génère accroche personnalisée (LLM) et
bascule en 'brouillon'. N'ENVOIE JAMAIS rien.
- Étude de cas ONG culturelle/éducative -> académies de musique Moodle
- Angle IA/automatisation -> serveur automatisé par IA
- Sans clé LLM : gabarit local déterministe (dry-run / tests).
Usage:
  python3 scripts/personalize.py [--limit 15] [--force] [--lead-id 3]
"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_conn, now_iso, env_int, load_dotenv

load_dotenv()

CASE_MOODLE = (
    "3 serveurs Moodle déployés et administrés pour des académies de musique "
    "internationales (mozambique.music-crossroads-academy.net, "
    "learn.global-music-campus.net, moodle.enset.work)"
)
CASE_IA = "un serveur automatisé par IA déployé et opéré en production (serveur.enset.work)"

PAYS_FR = {"madagascar", "france", "belgique", "suisse", "canada", "sénégal", "senegal",
           "côte d'ivoire", "cote d'ivoire", "cameroun", "mali", "burkina", "togo", "bénin",
           "benin", "rwanda", "burundi", "rdc", "congo", "maroc", "tunisie", "algérie", "algerie",
           "haïti", "haiti", "luxembourg", "monaco"}

MOTS_CULTURELS = {"culture", "music", "musique", "art", "ong", "ngo", "nonprofit",
                  "non-profit", "association", "foundation", "fondation", "éduc", "educ",
                  "school", "école", "academ"}
MOTS_IA = {"automat", "ai", "ia", "chatbot", "agent", "workflow", "digital", "numérique",
           "modernis", "edtech", "saas", "tech"}


def angle_pour(lead: dict) -> str:
    texte = f"{lead.get('secteur','')} {lead.get('poste','')} {lead.get('organisation','')}".lower()
    score_culture = sum(1 for m in MOTS_CULTURELS if m in texte)
    score_ia = sum(1 for m in MOTS_IA if m in texte)
    # Priorité 1 du brief : ONG culturelles/éducatives -> cas Moodle musique
    if score_culture > 0 and score_ia == 0:
        return "moodle"
    if score_ia > score_culture:
        return "ia"
    return "moodle"  # défaut : cas Moodle (offre principale)


def langue_pour(lead: dict) -> str:
    if (lead.get("pays") or "").strip().lower() in PAYS_FR:
        return "fr"
    return "en"


def prompt_pour(lead: dict, angle: str, lang: str) -> str:
    name = os.getenv("FREELANCER_NAME", "[TON NOM]")
    role = os.getenv("FREELANCER_ROLE", "Développeur Moodle & Automatisation IA — basé à Madagascar")
    cas = CASE_MOODLE if angle == "moodle" else CASE_IA
    if lang == "fr":
        return (
            f"Tu es {name}, {role}.\n"
            f"Rédige un email de prospection à froid COURT (120-150 mots), en français, ton professionnel et chaleureux.\n"
            f"Cible : {lead.get('contact')} ({lead.get('poste')}) — {lead.get('organisation')}, "
            f"{lead.get('secteur')}, {lead.get('pays')}.\n"
            f"Mets en avant l'expérience pertinente : {cas}.\n"
            f"Structure : accroche personnalisée (1 phrase sur leur mission) / preuve (1 phrase) / "
            f"proposition d'appel 20 min (1 phrase) / signature.\n"
            f"Objet proposé en première ligne sous la forme 'Objet: ...'. Pas de mensonge, pas de promesse chiffrée."
        )
    return (
        f"You are {name}, {role}.\n"
        f"Write a SHORT cold outreach email (120-150 words), in English, professional and warm.\n"
        f"Target: {lead.get('contact')} ({lead.get('poste')}) — {lead.get('organisation')}, "
        f"{lead.get('secteur')}, {lead.get('pays')}.\n"
        f"Highlight relevant experience: {cas}.\n"
        f"Structure: personalized hook (1 sentence on their mission) / proof (1 sentence) / "
        f"20-min call proposal (1 sentence) / signature.\n"
        f"First line as 'Subject: ...'. No lies, no invented metrics."
    )


def appel_llm(prompt: str) -> str | None:
    provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
    try:
        if provider == "openai":
            return _appel_openai(prompt)
        return _appel_anthropic(prompt)
    except Exception as e:
        print(f"LLM erreur ({provider}) : {e} — repli gabarit local.")
        return None


def _appel_anthropic(prompt: str) -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY vide")
    body = {
        "model": os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001"),
        "max_tokens": env_int("LLM_MAX_TOKENS", 600),
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()


def _appel_openai(prompt: str) -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY vide")
    body = {
        "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
        "max_tokens": env_int("LLM_MAX_TOKENS", 600),
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    return data["choices"][0]["message"]["content"].strip()


def gabarit_local(lead: dict, angle: str, lang: str) -> str:
    """Repli déterministe sans clé LLM (tests / dry-run)."""
    name = os.getenv("FREELANCER_NAME", "[TON NOM]")
    contact = lead.get("contact") or "there"
    org = lead.get("organisation") or "your organisation"
    cas = CASE_MOODLE if angle == "moodle" else CASE_IA
    if lang == "fr":
        return (
            f"Objet : Votre plateforme Moodle — retour d'expérience concret\n\n"
            f"Bonjour {contact},\n\n"
            f"Je suis {name}, développeur Moodle & automatisation IA basé à Madagascar. "
            f"En voyant la mission de {org}, je me suis dit que mon expérience pourrait vous être utile : {cas}.\n\n"
            f"Si vous modernisez votre formation à distance (Moodle, automatisations, assistants IA), "
            f"je peux auditer votre plateforme actuelle et proposer un plan concret.\n\n"
            f"Seriez-vous disponible pour un appel de 20 minutes cette semaine ?\n\n"
            f"Cordialement,\n{name}"
        )
    return (
        f"Subject: Your Moodle platform — concrete field experience\n\n"
        f"Hi {contact},\n\n"
        f"I'm {name}, a Moodle developer & AI automation specialist based in Madagascar. "
        f"Seeing {org}'s mission, I thought my experience could help: {cas}.\n\n"
        f"If you're modernizing distance learning (Moodle, automations, AI assistants), "
        f"I can audit your current platform and propose a concrete plan.\n\n"
        f"Would you be open to a 20-minute call this week?\n\n"
        f"Best regards,\n{name}"
    )


def message_linkedin(lead: dict, angle: str, lang: str) -> str:
    org = lead.get("organisation") or "your organisation"
    name = os.getenv("FREELANCER_NAME", "[TON NOM]")
    if lang == "fr":
        return (f"Bonjour {lead.get('contact') or ''}, je travaille avec des organisations éducatives "
                f"sur Moodle + IA ({'académies de musique internationales' if angle=='moodle' else 'serveurs automatisés par IA'}). "
                f"Intéressé par un échange de 20 min sur {org} ? — {name} (ENVOI MANUEL — ne pas automatiser)")
    return (f"Hi {lead.get('contact') or ''}, I help education orgs with Moodle + AI "
            f"({'intl. music academies' if angle=='moodle' else 'AI-automated servers'}). "
            f"Open to a 20-min chat about {org}? — {name} (MANUAL SEND ONLY — do not automate)")


def personnaliser(lead_id: int | None = None, limit: int = 15, force: bool = False) -> int:
    conn = get_conn()
    if lead_id:
        rows = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchall()
    elif force:
        rows = conn.execute(
            "SELECT * FROM leads WHERE statut IN ('nouveau','brouillon') ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM leads WHERE statut='nouveau' ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
    n = 0
    for r in rows:
        lead = dict(r)
        angle = angle_pour(lead)
        lang = langue_pour(lead)
        texte = appel_llm(prompt_pour(lead, angle, lang)) or gabarit_local(lead, angle, lang)
        li = message_linkedin(lead, angle, lang)
        ts = now_iso()
        conn.execute(
            """UPDATE leads SET message_genere=?, linkedin_message=?,
               statut='brouillon', date_derniere_action=?, updated_at=? WHERE id=?""",
            (texte, li, ts, ts, lead["id"]),
        )
        n += 1
        print(f"lead {lead['id']} ({lead['email']}) -> brouillon [angle={angle} lang={lang}]")
    conn.commit()
    conn.close()
    print(f"{n} message(s) en BROUILLON — validation humaine requise, rien n'est envoyé.")
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=env_int("WEEKLY_LEAD_TARGET", 12))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--lead-id", type=int, default=None)
    a = ap.parse_args()
    personnaliser(a.lead_id, a.limit, a.force)


if __name__ == "__main__":
    main()
