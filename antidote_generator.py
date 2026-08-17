import sqlite3
import re
from datetime import datetime

db = sqlite3.connect('/root/cyberia/.cyberia/payload_lab.db')
cur = db.cursor()

# Récupérer les payloads qui bypassent tous les WAF
cur.execute("""
    SELECT id, payload, category, bypasses 
    FROM payloads 
    WHERE bypasses >= 23
    ORDER BY score DESC
""")
elite = cur.fetchall()

antidotes = []
for pid, payload, category, bypasses in elite:
    escaped = re.escape(payload[:80])
    antidotes.append((
        None,           # id
        pid,            # payload_id
        category,       # waf_name (catégorie source)
        escaped,        # detection_rule
        95.0,           # effectiveness
        datetime.now().isoformat()  # created_at
    ))

cur.executemany(
    'INSERT OR IGNORE INTO antidotes VALUES (?,?,?,?,?,?)', 
    antidotes
)
db.commit()

cur.execute('SELECT COUNT(*) FROM antidotes')
total = cur.fetchone()[0]
print(f'[ANTIDOTES] {len(antidotes)} nouveaux | Total: {total}')
db.close()
