# Prospection freelance — Moodle + IA

Système local d'automatisation de prospection (email à froid + LinkedIn semi-manuel)
pour un développeur basé à Madagascar, offre **Moodle (LMS) + automatisation IA**.

- **10–15 leads/semaine** pour démarrer, **10–15 emails/jour max**
- **Aucun envoi sans validation humaine** pendant les 3 premières semaines (`REQUIRE_APPROVAL=true`)
- **Mode dry-run par défaut** : tout est logué, rien n'est envoyé (`DRY_RUN=true`)
- Secrets **uniquement** en variables d'environnement (`.env`, jamais en dur)
- Pensé pour une **migration VPS + domaine** sans réécriture (voir § 7)

## 1. Architecture

```
┌─────────────┐   CSV / Apollo    ┌────────────┐  LLM (ou gabarit)  ┌───────────┐
│ W1 Sourcing │ ───────────────▶ │   leads.db │ ─────────────────▶ │ BROUILLON │
└─────────────┘   statut nouveau  │  (SQLite)  │  statut brouillon  └─────┬─────┘
                                  └────────────┘                          │ validation humaine
┌─────────────┐   IMAP polling    ┌────────────┐   SMTP Gmail       ┌──────▼──────┐
│ W5 Réponses │ ◀─────────────── │ hsavatra@  │ ◀──────────────── │ W3 Envoi    │
│ + Telegram  │   statut repondu  │  gmail.com │  quota 12/j + log │ (approuvés) │
└─────────────┘                   └────────────┘                   └─────────────┘
                                          ▲  J+3 / J+7, max 2    ┌─────────────┐
                                          └────────────────────── │ W4 Relances │
                                                                 └─────────────┘
```

Deux couches qui partagent la **même base SQLite** et la **même logique** :
- **`scripts/*.py`** (stdlib uniquement) : utilisables directement en CLI / cron, même si n8n est éteint.
- **n8n local** (Docker, `http://localhost:5678`) : 5 workflows (`n8n-workflows/*.json`)
  qui appellent ces mêmes scripts via le node *Execute Command* (planifiés, **jamais de webhooks**).

| Fichier | Rôle |
|---|---|
| `scripts/sourcing.py` | W1 : import CSV + Apollo/Hunter |
| `scripts/personalize.py` | W2 : messages IA → `brouillon` (n'envoie jamais) |
| `scripts/send.py` | W3 : envoi SMTP des `approuve`, quota, LinkedIn manuel |
| `scripts/followup.py` | W4 : relances J+3/J+7, max 2, textes différents |
| `scripts/check_replies.py` | W5 : IMAP polling → `repondu` + notif Telegram |
| `scripts/stats.py` | stats par statut / jour / type |
| `scripts/init_db.py` | crée la base (idempotent) |
| `data/leads.db` | base SQLite (créée au 1er run) |
| `data/leads_import.csv` | modèle d'import (adresses d'exemple) |

## 2. Installation

Prérequis : Docker + Python 3 (stdlib uniquement, rien à installer via pip).

```bash
cd /home/Hsavatra/Bureau/n8n   # ou le dossier du projet sur une autre machine
cp .env.example .env
# → éditer .env : N8N_ENCRYPTION_KEY (openssl rand -hex 32),
#   FREELANCER_NAME (remplace [TON NOM]), puis les clés quand disponibles
#   (SMTP_APP_PASSWORD, ANTHROPIC_API_KEY ou OPENAI_API_KEY, APOLLO_API_KEY,
#    TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)

python3 scripts/init_db.py
docker compose up -d --build   # 1er build ≈ 15 min (npm installe n8n : ~2200 paquets)
# → n8n sur http://localhost:5678 (créer le compte propriétaire au 1er lancement ;
#   aucun accès anonyme, même en local)
```

> **Notes image Docker**
> - L'image officielle `n8nio/n8n` actuelle est *hardened* (sans shell ni
>   gestionnaire de paquets) : on ne peut pas y ajouter python3. Le
>   `Dockerfile.n8n` construit donc `node:22-alpine + python3 + npm i -g n8n`.
> - `npm i -g n8n` installe la **v2** (2026), qui **désactive le node
>   ExecuteCommand par défaut** (breaking change sécurité). Le
>   `docker-compose.yml` le réactive explicitement (`NODES_EXCLUDE=[]`),
>   choix volontaire et documenté : instance locale mono-utilisateur, scripts
>   montés en lecture seule. À la migration VPS, conservez ce réglage
>   (votre VPS = votre machine) ou remplacez les ExecuteCommand par des nodes
>   natifs si vous durcissez l'instance.

Importer les workflows dans n8n : **Workflows → ⋯ → Import from file**,
puis **activer** chaque workflow (interrupteur *Active*) :
`n8n-workflows/w1-sourcing.json` … `w5-reponses.json`.

Sans Docker (repli prévu par le brief) : `npx n8n` + `python3 scripts/*.py` en cron.

## 3. Ajouter un lead

**Option A — CSV (recommandé pour démarrer) :**
```bash
# éditer data/leads_import.csv (colonnes : organisation,contact,email,poste,secteur,pays)
python3 scripts/sourcing.py --csv ./data/leads_import.csv
```

**Option B — Apollo (quand `APOLLO_API_KEY` est renseigné) :**
```bash
python3 scripts/sourcing.py --apollo --limit 12
```

**Option C — Hunter :** enrichissement des emails manquants
(`python3 scripts/sourcing.py --enrich-hunter` ; le *Email-Finder* exige
domaine + nom : les cas non résolvables sont signalés pour saisie manuelle).

Statut initial : `nouveau`. Doublons (email) ignorés automatiquement.

## 4. Valider un message avant envoi (obligatoire, 3 semaines min)

```bash
python3 scripts/personalize.py          # nouveau → brouillon (IA ou gabarit local)
python3 scripts/send.py --list          # voir la file à valider
# → relire chaque brouillon :
python3 -c "import sqlite3; c=sqlite3.connect('data/leads.db');
print(c.execute(\"SELECT message_genere FROM leads WHERE id=1\").fetchone()[0])"
python3 scripts/send.py --approve 1     # validation humaine, lead par lead
python3 scripts/send.py --send          # envoi (dry-run par défaut, quota 12/j)

# LinkedIn (TOUJOURS manuel) :
python3 scripts/send.py --linkedin 1    # copier-coller à la main, jamais d'auto-envoi

# Relances : préparer → valider → envoyer
python3 scripts/followup.py --prepare
python3 scripts/followup.py --approve 1 --num 1
python3 scripts/followup.py --send
```

Tant que `REQUIRE_APPROVAL=true` (défaut), **rien ne part sans `--approve`**.
Pour sortir du mode validation après 3 semaines : `REQUIRE_APPROVAL=false` dans `.env`.

## 5. Suivi des statistiques

```bash
python3 scripts/stats.py
# leads par statut (nouveau/brouillon/approuve/contacte/relance/repondu/converti/perdu),
# envois réels par jour, envois par type, taux de réponse.
```

Réponses : `check_replies.py` (ou workflow W5 toutes les 30 min) passe les leads
en `repondu` et envoie un résumé sur Telegram. Marquer un succès à la main :
```bash
python3 -c "import sqlite3; c=sqlite3.connect('data/leads.db');
c.execute(\"UPDATE leads SET statut='converti' WHERE id=1\"); c.commit()"
```

## 6. Dry-run & garde-fous

| Garde-fou | Où | Défaut |
|---|---|---|
| Dry-run (logue sans envoyer) | `DRY_RUN` | `true` |
| Validation humaine requise | `REQUIRE_APPROVAL` | `true` |
| Quota journalier (compte `email_log` du jour) | `DAILY_SEND_LIMIT` | `12` |
| Relances max / lead, J+3 / J+7 | `FOLLOWUP_MAX`, `FOLLOWUP_DAY_1/2` | `2`, `3` / `7` |
| Données minimales (7 champs + statut + message) | schéma `leads` | — |
| Pas de webhook public en local | triggers Schedule/IMAP uniquement | — |

Passer en réel : `DRY_RUN=false` dans `.env` (+ mot de passe d'application Gmail :
*Compte Google → Sécurité → Validation en 2 étapes → Mots de passe d'application* ;
**jamais** le mot de passe principal).

## 7. Migration VPS + domaine (plus tard)

Rien n'est codé en dur pour la machine locale : chemins via `LEADS_DB_PATH`,
secrets via env, triggers sans webhook. Le jour J :

1. Louer un VPS + acheter un domaine dédié (ne **jamais** prospecter depuis gmail
   à terme : chauffer le domaine 2–4 semaines, SPF/DKIM/DMARC).
2. Copier le projet, `cp .env.example .env`, renseigner les secrets, changer
   `LEADS_DB_PATH` si besoin (ou basculer sur Postgres : monter un service
   `db` dans `docker-compose.yml`, les workflows suivent via env).
3. `docker compose up -d --build` (ajouter `WEBHOOK_URL=https://…` + reverse
   proxy TLS type Caddy/Traefik pour activer les webhooks entrants si souhaité).
4. Baisser progressivement `DAILY_SEND_LIMIT` au démarrage du domaine (ex. 20/j),
   garder `REQUIRE_APPROVAL=true` une semaine après migration.
5. `graphify update .` — n/a ici (pas de graphe sur ce projet).

## 8. Dépannage

- `SMTP/IMAP manquants` → remplir `SMTP_APP_PASSWORD` (mot de passe d'application).
- `ANTHROPIC_API_KEY vide — repli gabarit local` → normal sans clé ; mettre une
  clé `ANTHROPIC_API_KEY` ou `OPENAI_API_KEY` (+ `LLM_PROVIDER=openai`) pour l'IA réelle.
- `Quota journalier atteint` → normal, reprise le lendemain (anti-spam Gmail).
- n8n injoignable → `docker compose ps && docker compose logs n8n | tail -30`.
- Build Docker sans paquets (`apk/apt-get not found`) → ne pas utiliser
  `n8nio/n8n` directement, garder le `Dockerfile.n8n` (voir § 2).

## 9. Secrets à fournir (variables d'environnement, `.env`)

`SMTP_APP_PASSWORD` (Gmail, mot de passe d'application) · `ANTHROPIC_API_KEY`
ou `OPENAI_API_KEY` · `APOLLO_API_KEY` / `HUNTER_API_KEY` · `TELEGRAM_BOT_TOKEN`
+ `TELEGRAM_CHAT_ID` · `FREELANCER_NAME` (remplace `[TON NOM]` partout).
