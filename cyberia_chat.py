import sqlite3, os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv('/root/cyberia/.env')
client = OpenAI(
    api_key=os.getenv('OPENROUTER_API_KEY'),
    base_url='https://openrouter.ai/api/v1'
)

VERITE = '/root/cyberia/.cyberia/cyberia_verite.md'

def get_context():
    # Lire le fichier de verite (source de reference unique et propre)
    verite = ""
    try:
        with open(VERITE, 'r') as f:
            verite = f.read()
    except:
        verite = "(fichier de verite introuvable)"
    return f"""Tu es CYBERIA, IA experte en cybersecurite defensive creee par Yoro.

Ton savoir se base UNIQUEMENT sur le fichier de verite ci-dessous. Il fait autorite.
Tu ne parles JAMAIS de "23 WAF", de "payloads DIAMOND" ni "d'antidotes" : ce sont
des mythes de l'ancien systeme, PROUVES FAUX. Si tu ne sais pas, tu le dis.
Tu ne fais aucune fausse affirmation de capacite. Tu reponds en francais, professionnel.

=== FICHIER DE VERITE ===
{verite}
=== FIN DU FICHIER DE VERITE ==="""

history = []
context = get_context()
print("=== CYBERIA IA === (tape 'exit' pour quitter)")
print(f"Contexte charge depuis le fichier de verite.\n")

while True:
    question = input("Toi: ").strip()
    if question.lower() == 'exit':
        break
    if not question:
        continue
    history.append({'role': 'user', 'content': question})
    try:
        resp = client.chat.completions.create(
            model='deepseek/deepseek-chat',
            messages=[{'role': 'system', 'content': context}] + history[-10:],
            max_tokens=500
        )
        answer = resp.choices[0].message.content
        history.append({'role': 'assistant', 'content': answer})
        print(f"\nCYBERIA: {answer}\n")
    except Exception as e:
        print(f"Erreur: {e}")
