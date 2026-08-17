import sqlite3
import json
from datetime import datetime

db = sqlite3.connect('/root/cyberia/.cyberia/payload_lab.db')
cur = db.cursor()

cur.execute("""
    SELECT waf_name, detection_rule, effectiveness 
    FROM antidotes 
    WHERE effectiveness >= 90
    ORDER BY effectiveness DESC
""")
antidotes = cur.fetchall()

# Format ModSecurity
modsec_rules = []
for i, (waf_name, rule, effectiveness) in enumerate(antidotes):
    modsec_rules.append(
        f'SecRule REQUEST_URI|ARGS|REQUEST_BODY "{rule}" '
        f'"id:{900100+i},phase:2,deny,status:403,'
        f'msg:\'CYBERIA-WAF-{waf_name.upper()}\'"'
    )

with open('/root/cyberia/.cyberia/cyberia_waf.conf', 'w') as f:
    f.write('\n'.join(modsec_rules))

# Format JSON pour dashboard
waf_json = {
    'generated_at': datetime.now().isoformat(),
    'total_rules': len(antidotes),
    'rules': [{'category': w, 'pattern': r, 'score': e} 
              for w, r, e in antidotes]
}

with open('/root/cyberia/.cyberia/cyberia_waf.json', 'w') as f:
    json.dump(waf_json, f, indent=2)

print(f'[WAF] {len(antidotes)} règles générées')
print(f'  → /root/cyberia/.cyberia/cyberia_waf.conf (ModSecurity)')
print(f'  → /root/cyberia/.cyberia/cyberia_waf.json (Dashboard)')
db.close()
