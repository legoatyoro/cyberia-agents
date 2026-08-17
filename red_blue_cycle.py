import sqlite3
import re
import json
from datetime import datetime

db = sqlite3.connect('/root/cyberia/.cyberia/payload_lab.db')
cur = db.cursor()

print(f'[RED/BLUE] Cycle démarré : {datetime.now().isoformat()}')

# ÉTAPE 1 — Lire les nouveaux payloads qui bypassent 23/23 WAF
cur.execute("""
    SELECT id, payload, category, bypasses, score
    FROM payloads 
    WHERE bypasses >= 20
    AND created_at > datetime('now', '-2 hours')
    ORDER BY score DESC
    LIMIT 100
""")
new_elite = cur.fetchall()
print(f'[RED] {len(new_elite)} nouveaux payloads élite détectés')

# ÉTAPE 2 — Générer antidotes depuis ces payloads
antidotes_added = 0
for pid, payload, category, bypasses, score in new_elite:
    escaped = re.escape(payload[:80])
    try:
        cur.execute(
            'INSERT OR IGNORE INTO antidotes VALUES (?,?,?,?,?,?)',
            (None, pid, category, escaped, min(95.0, float(score or 50)), 
             datetime.now().isoformat())
        )
        antidotes_added += 1
    except:
        pass

db.commit()
print(f'[BLUE] {antidotes_added} nouveaux antidotes générés')

# ÉTAPE 3 — Stats globales
cur.execute('SELECT COUNT(*) FROM payloads WHERE bypasses >= 20')
elite_count = cur.fetchone()[0]

cur.execute('SELECT COUNT(*) FROM antidotes')
antidote_count = cur.fetchone()[0]

cur.execute('SELECT AVG(bypasses) FROM payloads WHERE created_at > datetime("now", "-24 hours")')
avg_bypass = cur.fetchone()[0] or 0

print(f'[STATS] Payloads élite: {elite_count} | Antidotes: {antidote_count}')
print(f'[STATS] Bypass moyen 24h: {avg_bypass:.1f}/23 WAF')
print(f'[STATS] Évolution: {"✅ En progression" if avg_bypass > 15 else "⚠️ Stagnation détectée"}')

# ÉTAPE 4 — Détecter la stagnation
if avg_bypass < 10:
    print('[ALERT] Stagnation détectée — rotation des prompts nécessaire')
    # Écrire un signal pour evolve_live_v2
    with open('/root/cyberia/.cyberia/supervisor_prompts.json', 'r') as f:
        prompts = json.load(f)
    prompts['stagnation_detected'] = True
    prompts['stagnation_at'] = datetime.now().isoformat()
    with open('/root/cyberia/.cyberia/supervisor_prompts.json', 'w') as f:
        json.dump(prompts, f, indent=2)

db.close()
print(f'[RED/BLUE] Cycle terminé')
