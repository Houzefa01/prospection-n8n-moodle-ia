#!/usr/bin/env python3
"""Statistiques de suivi. Usage: python3 scripts/stats.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import get_conn

conn = get_conn()
print("=== LEADS par statut ===")
for r in conn.execute("SELECT statut, COUNT(*) c FROM leads GROUP BY statut ORDER BY c DESC"):
    print(f"  {r['statut']:10} {r['c']}")
print("\n=== EMAILS envoyés par jour (réels, hors dry-run) ===")
for r in conn.execute(
    "SELECT substr(sent_at,1,10) jour, COUNT(*) c FROM email_log "
    "WHERE dry_run=0 GROUP BY jour ORDER BY jour DESC LIMIT 14"
):
    print(f"  {r['jour']}  {r['c']} envoi(s)")
print("\n=== ENVOIS par type (7 derniers jours, dry-run inclus) ===")
for r in conn.execute(
    "SELECT type_envoi, COUNT(*) c FROM email_log "
    "WHERE sent_at >= date('now','-7 days') GROUP BY type_envoi"
):
    print(f"  {r['type_envoi']:10} {r['c']}")
n = conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
rep = conn.execute("SELECT COUNT(*) c FROM leads WHERE statut='repondu'").fetchone()["c"]
print(f"\nTotal leads : {n} | Réponses : {rep} | Taux : {rep/max(n,1)*100:.1f}%")
conn.close()
