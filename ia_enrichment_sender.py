import sqlite3
import os
import json
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime

load_dotenv('/root/cyberia/.env')

client = OpenAI(
    api_key=os.getenv('OPENROUTER_API_KEY'),
    base_url='https://openrouter.ai/api/v1'
)

db = sqlite3.connect('/root/cyberia/.cyberia/payload_lab.db')
cur = db.cursor()

# Récupérer les meilleurs payloads récents
cur.execute("""
    SELECT category, payload, bypasses, score
    FROM payloads 
    WHERE bypasses >= 20
    AND created_at > datetime('now', '-1 hour')
    ORDER BY bypasses DESC, score DESC
    LIMIT 20
""")
recent_elite = cur.fetchall()

# Récupérer les antidotes récents
cur.execute("""
    SELECT waf_name, detection_rule, effectiveness
    FROM antidotes
    WHERE created_at > datetime('now', '-1 hour')
    ORDER BY effectiveness DESC
    LIMIT 10
""")
recent_antidotes = cur.fetchall()

if not recent_elite and not recent_antidotes:
    print('[ENRICHMENT] Pas de nouvelles données dans la dernière heure')
    db.close()
    exit()

# Construire le contexte d'enrichissement
context = f"""
RAPPORT D'ENRICHISSEMENT CYBERIA — {datetime.now().isoformat()}

NOUVEAUX PAYLOADS ELITE ({len(recent_elite)}) :
"""
for cat, payload, bypasses, score in recent_elite:
    context += f"- [{cat}] bypass {bypasses}/23 | score {score} : {payload[:60]}\n"

context += f"\nNOUVEAUX ANTIDOTES ({len(recent_antidotes)}) :\n"
for waf, rule, effectiveness in recent_antidotes:
    context += f"- [{waf}] efficacité {effectiveness}% : {rule[:60]}\n"

# Envoyer à l'IA pour analyse et enrichissement mémoire
prompt = f"""Tu es CYBERIA, expert en cybersécurité défensive.
Voici les nouvelles données générées par tes laboratoires :

{context}

Analyse ces données et produis :
1. Un résumé des nouvelles techniques détectées
2. Les patterns émergents observés
3. Les recommandations pour améliorer les WAF
4. Les catégories qui nécessitent plus de génération

Réponds en français, de façon concise et technique."""

try:
    resp = client.chat.completions.create(
        model='deepseek/deepseek-chat',
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=500
    )
    analysis = resp.choices[0].message.content
    
    # Sauvegarder l'analyse
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    with open(f'/root/cyberia/.cyberia/ia_analysis_{timestamp}.txt', 'w') as f:
        f.write(f"=== ANALYSE IA {timestamp} ===\n\n")
        f.write(context)
        f.write(f"\n=== RÉPONSE IA ===\n\n")
        f.write(analysis)
    
    print(f'[ENRICHMENT] Analyse sauvegardée : ia_analysis_{timestamp}.txt')
    print(f'\n{analysis[:300]}...')
    
except Exception as e:
    print(f'[ENRICHMENT] Erreur: {e}')

db.close()
