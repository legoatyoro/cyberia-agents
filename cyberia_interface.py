import sqlite3, os
from flask import Flask, request, jsonify, render_template_string
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv('/root/cyberia/.env')
client = OpenAI(
    api_key=os.getenv('DEEPSEEK_API_KEY'),
    base_url='https://api.deepseek.com'
)
app = Flask(__name__)
import json, os
MEMORY_FILE = "/root/cyberia/.cyberia/sessions.json"
conversations = json.load(open(MEMORY_FILE)) if os.path.exists(MEMORY_FILE) else {}

HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CYBERIA IA</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{background:#080b0f;color:#e6edf3;font-family:'Segoe UI',sans-serif;height:100vh;display:flex;flex-direction:column;}
header{background:#0d1117;border-bottom:1px solid #21262d;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;}
.logo{color:#00ff88;font-size:20px;font-weight:700;letter-spacing:2px;font-family:'Courier New',monospace;}
.stats{display:flex;gap:16px;}
.stat{background:#161b22;border:1px solid #21262d;border-radius:6px;padding:6px 12px;font-size:12px;color:#7d8590;}
.stat span{color:#00ff88;font-weight:bold;}
#messages{flex:1;overflow-y:auto;padding:24px;display:flex;flex-direction:column;gap:16px;scroll-behavior:smooth;}
#messages::-webkit-scrollbar{width:4px;}
#messages::-webkit-scrollbar-thumb{background:#21262d;border-radius:2px;}
.msg{max-width:80%;padding:16px 20px;border-radius:12px;font-size:15px;line-height:1.7;}
.msg.user{background:#1a2636;border:1px solid #58a6ff44;align-self:flex-end;}
.msg.bot{background:#0d1a12;border:1px solid #00ff8844;align-self:flex-start;}
.sender{font-size:11px;font-weight:700;margin-bottom:8px;letter-spacing:1px;}
.msg.bot .sender{color:#00ff88;}
.msg.user .sender{color:#58a6ff;}
.msg p{margin-bottom:8px;}
.msg p:last-child{margin-bottom:0;}
.msg strong{color:#00ff88;}
.msg code{background:#161b22;padding:2px 6px;border-radius:4px;font-family:'Courier New',monospace;font-size:13px;color:#ffd166;}
.msg pre{background:#050709;border:1px solid #21262d;padding:14px;border-radius:8px;overflow-x:auto;margin:10px 0;}
.msg pre code{background:none;padding:0;color:#00ff88;font-size:13px;}
.suggestions{padding:0 24px 12px;display:flex;gap:8px;flex-wrap:wrap;}
.sug{background:#161b22;border:1px solid #21262d;border-radius:20px;padding:6px 14px;font-size:12px;cursor:pointer;color:#7d8590;transition:all .2s;}
.sug:hover{border-color:#00ff88;color:#00ff88;}
.typing{padding:0 24px 8px;font-size:13px;color:#00ff88;display:none;}
footer{background:#0d1117;border-top:1px solid #21262d;padding:16px 24px;display:flex;gap:12px;align-items:flex-end;}
#input{flex:1;background:#161b22;border:1px solid #21262d;border-radius:10px;padding:14px 18px;color:#e6edf3;font-family:'Segoe UI',sans-serif;font-size:15px;outline:none;resize:none;min-height:52px;max-height:120px;line-height:1.5;}
#input:focus{border-color:#00ff88;}
#send{background:#00ff88;color:#000;border:none;border-radius:10px;padding:14px 28px;font-weight:700;cursor:pointer;font-size:15px;white-space:nowrap;}
#send:hover{background:#00ffaa;}
</style>
</head>
<body>
<header>
  <div class="logo">⚡ CYBERIA IA</div>
  <div class="stats">
    <div class="stat">Payloads <span id="s1">-</span></div>
    <div class="stat">Élite <span id="s2">-</span></div>
    <div class="stat">Antidotes <span id="s3">-</span></div>
  </div>
</header>

<div id="messages">
  <div class="msg bot">
    <div class="sender">CYBERIA</div>
    <p>Bonjour ! Je suis <strong>CYBERIA</strong>, ton IA experte en cybersécurité défensive.</p>
    <p>Je connais ta base de payloads, tes antidotes WAF et tes résultats de scans. Comment puis-je t'aider ?</p>
  </div>
</div>

<div class="suggestions">
  <div class="sug" onclick="suggest(this)">Stats de ma DB payloads</div>
  <div class="sug" onclick="suggest(this)">Meilleurs payloads SQLi</div>
  <div class="sug" onclick="suggest(this)">Analyse SSRF avancé</div>
  <div class="sug" onclick="suggest(this)">Rapport client vulnérabilités</div>
  <div class="sug" onclick="suggest(this)">Comment améliorer mes WAF</div>
</div>

<div class="typing" id="typing">⚡ CYBERIA réfléchit...</div>

<footer>
  <textarea id="input" placeholder="Pose une question à CYBERIA..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}"></textarea>
  <button id="send" onclick="send()">Envoyer</button>
</footer>

<script>
const msgs = document.getElementById('messages');

async function loadStats(){
  const r = await fetch('/stats');
  const d = await r.json();
  document.getElementById('s1').textContent = d.total.toLocaleString();
  document.getElementById('s2').textContent = d.elite.toLocaleString();
  document.getElementById('s3').textContent = d.antidotes.toLocaleString();
}
loadStats();
setInterval(loadStats, 30000);

function suggest(el){ document.getElementById('input').value = el.textContent; }

function formatText(text){
  return text
    .replace(/```(\\w*)\\n?([\\s\\S]*?)```/g, '<pre><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
    .replace(/\\n/g, '</p><p>');
}

function addMsg(role, text){
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  const sender = role === 'user' ? 'TOI' : 'CYBERIA';
  div.innerHTML = '<div class="sender">' + sender + '</div><p>' + formatText(text) + '</p>';
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}

async function send(){
  const q = document.getElementById('input').value.trim();
  if(!q) return;
  document.getElementById('input').value = '';
  addMsg('user', q);
  document.getElementById('typing').style.display = 'block';
  msgs.scrollTop = msgs.scrollHeight;
  try{
    const r = await fetch('/chat', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:q})
    });
    const d = await r.json();
    document.getElementById('typing').style.display = 'none';
    addMsg('bot', d.response);
  }catch(e){
    document.getElementById('typing').style.display = 'none';
    addMsg('bot', 'Erreur de connexion.');
  }
}
</script>
</body>
</html>"""

def get_context():
    # Lit le fichier de verite (source propre unique)
    try:
        with open('/root/cyberia/.cyberia/cyberia_verite.md','r') as f:
            verite = f.read()
    except:
        verite = '(fichier de verite introuvable)'
    return f"""Tu es CYBERIA, IA experte en cybersecurite defensive creee par Yoro.

Ton savoir se base UNIQUEMENT sur le fichier de verite ci-dessous, qui fait autorite.
Tu ne parles JAMAIS de "23 WAF", "payloads DIAMOND" ni "antidotes" : mythes de
l'ancien systeme PROUVES FAUX. Si une info n'y est pas, tu dis que tu ne sais pas.
Aucune fausse affirmation de capacite. Reponds en francais, concis et structure.

=== FICHIER DE VERITE ===
{verite}
=== FIN ==="""

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/stats')
def stats():
    db = sqlite3.connect('/root/cyberia/.cyberia/payload_lab.db')
    cur = db.cursor()
    cur.execute('SELECT COUNT(*) FROM payloads')
    total = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM payloads WHERE bypasses >= 23')
    elite = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM antidotes')
    antidotes = cur.fetchone()[0]
    db.close()
    return jsonify({'total':total,'elite':elite,'antidotes':antidotes})

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    message = data.get('message','')
    session_id = request.remote_addr
    if session_id not in conversations:
        conversations[session_id] = []
    conversations[session_id].append({'role':'user','content':message})
    try:
        resp = client.chat.completions.create(
            model='deepseek-chat',
            messages=[{'role':'system','content':get_context()}] + conversations[session_id][-8:],
            max_tokens=600
        )
        answer = resp.choices[0].message.content
        conversations[session_id].append({'role':'assistant','content':answer})
        return jsonify({'response':answer})
    except Exception as e:
        return jsonify({'response':f'Erreur: {str(e)}'})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=9999, debug=False)
