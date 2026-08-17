import sqlite3
import os
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime

load_dotenv('/root/cyberia/.env')

client = OpenAI(
    api_key=os.getenv('MIMO_API_KEY'),
    base_url='https://api.xiaomimimo.com/v1'
)

db = sqlite3.connect('/root/cyberia/.cyberia/payload_lab.db')
cur = db.cursor()

# Récupérer les meilleurs payloads par catégorie
cur.execute("""
    SELECT category, payload, bypasses 
    FROM payloads 
    WHERE bypasses >= 20 
    GROUP BY category 
    HAVING MAX(bypasses)
    LIMIT 10
""")
best = cur.fetchall()

for category, payload, bypasses in best:
    prompt = f"""Tu es un expert en cybersécurité défensive.
Analyse ce payload de type {category} qui bypass {bypasses}/23 WAF :
{payload[:100]}

En 3 phrases courtes explique :
1. Pourquoi ce payload est dangereux
2. Comment le WAF doit le détecter
3. La correction recommandée pour les développeurs"""

    try:
        resp = client.chat.completions.create(
            model='mimo-v2.5-pro',
            messages=[{'role': 'user', 'content': prompt}],
            max_tokens=200
        )
        analysis = resp.choices[0].message.content
        print(f'[{category}] {analysis[:150]}...')
        print('---')
    except Exception as e:
        print(f'[{category}] Erreur: {e}')

db.close()
