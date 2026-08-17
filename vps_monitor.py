import os, sqlite3, glob, subprocess
from flask import Flask, render_template_string
from datetime import datetime

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
<title>CYBERIA VPS Monitor</title>
<meta http-equiv="refresh" content="30">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#080b0f; color:#e6edf3; font-family:'Courier New',monospace; padding:20px; }
h1 { color:#00ff88; font-size:20px; margin-bottom:20px; border-bottom:1px solid #21262d; padding-bottom:10px; }
h2 { color:#58a6ff; font-size:14px; margin:16px 0 8px; }
.grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; margin-bottom:20px; }
.card { background:#0d1117; border:1px solid #21262d; border-radius:8px; padding:14px; }
.card .val { font-size:28px; font-weight:bold; color:#00ff88; }
.card .lbl { font-size:10px; color:#7d8590; margin-top:4px; }
.log { background:#050709; border:1px solid #21262d; border-radius:6px; padding:12px; font-size:11px; line-height:1.6; max-height:200px; overflow-y:auto; white-space:pre-wrap; }
.green { color:#00ff88; }
.red { color:#ff3b5c; }
.yellow { color:#ffd166; }
.blue { color:#58a6ff; }
table { width:100%; border-collapse:collapse; font-size:11px; }
th { background:#161b22; color:#00ff88; padding:6px 10px; text-align:left; }
td { padding:6px 10px; border-bottom:1px solid #21262d; }
</style>
</head>
<body>
<h1>⚡ CYBERIA VPS Monitor — {{ now }}</h1>

<div class="grid">
  <div class="card">
    <div class="val green">{{ stats.total }}</div>
    <div class="lbl">PAYLOADS TOTAL</div>
  </div>
  <div class="card">
    <div class="val green">{{ stats.elite }}</div>
    <div class="lbl">PAYLOADS ÉLITE (23/23)</div>
  </div>
  <div class="card">
    <div class="val blue">{{ stats.antidotes }}</div>
    <div class="lbl">ANTIDOTES WAF</div>
  </div>
  <div class="card">
    <div class="val yellow">{{ stats.avg_bypass }}</div>
    <div class="lbl">BYPASS MOYEN /23</div>
  </div>
  <div class="card">
    <div class="val green">{{ stats.last_hour }}</div>
    <div class="lbl">NOUVEAUX (1H)</div>
  </div>
  <div class="card">
    <div class="val {{ 'green' if screens > 0 else 'red' }}">{{ screens }}</div>
    <div class="lbl">LABS ACTIFS</div>
  </div>
</div>

<h2>Top catégories</h2>
<table>
<tr><th>Catégorie</th><th>Total</th><th>Élite (23/23)</th></tr>
{% for cat, total, elite in categories %}
<tr><td>{{ cat }}</td><td>{{ total }}</td><td class="green">{{ elite }}</td></tr>
{% endfor %}
</table>

<h2>Logs récents (evolve)</h2>
<div class="log">{{ evolve_log }}</div>

<h2>Analyses IA récentes</h2>
<div class="log">{{ ia_log }}</div>

<h2>Crontab</h2>
<div class="log">{{ crontab }}</div>

</body>
</html>
"""

@app.route('/')
def index():
    db = sqlite3.connect('/root/cyberia/.cyberia/payload_lab.db')
    cur = db.cursor()
    
    stats = {}
    cur.execute('SELECT COUNT(*) FROM payloads')
    stats['total'] = cur.fetchone()[0]
    
    cur.execute('SELECT COUNT(*) FROM payloads WHERE bypasses >= 23')
    stats['elite'] = cur.fetchone()[0]
    
    cur.execute('SELECT COUNT(*) FROM antidotes')
    stats['antidotes'] = cur.fetchone()[0]
    
    cur.execute('SELECT ROUND(AVG(bypasses),1) FROM payloads')
    stats['avg_bypass'] = cur.fetchone()[0] or 0
    
    cur.execute("SELECT COUNT(*) FROM payloads WHERE created_at > datetime('now', '-1 hour')")
    stats['last_hour'] = cur.fetchone()[0]
    
    cur.execute("""
        SELECT category, COUNT(*) as total,
               SUM(CASE WHEN bypasses >= 23 THEN 1 ELSE 0 END) as elite
        FROM payloads 
        GROUP BY category 
        ORDER BY total DESC 
        LIMIT 10
    """)
    categories = cur.fetchall()
    db.close()
    
    # Screens actifs
    try:
        result = subprocess.run(['screen', '-ls'], capture_output=True, text=True)
        screens = result.stdout.count('(Detached)')
    except:
        screens = 0
    
    # Logs evolve
    try:
        with open('/root/cyberia/.cyberia/evolve_main.log', 'r') as f:
            lines = f.readlines()
            evolve_log = ''.join(lines[-30:])
    except:
        evolve_log = 'Aucun log'
    
    # Analyses IA
    try:
        analyses = sorted(glob.glob('/root/cyberia/.cyberia/ia_analysis_*.txt'), reverse=True)
        if analyses:
            with open(analyses[0], 'r') as f:
                ia_log = f.read()[-800:]
        else:
            ia_log = 'Aucune analyse'
    except:
        ia_log = 'Erreur lecture'
    
    # Crontab
    try:
        result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        crontab = result.stdout
    except:
        crontab = 'Erreur'
    
    return render_template_string(HTML,
        now=datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
        stats=stats,
        screens=screens,
        categories=categories,
        evolve_log=evolve_log,
        ia_log=ia_log,
        crontab=crontab
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8888, debug=False)
