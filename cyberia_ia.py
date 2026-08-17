import sqlite3, os, json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv('/root/cyberia/.env')

client = OpenAI(
    api_key=os.getenv('DEEPSEEK_API_KEY'),
    base_url='https://api.deepseek.com'
)

def get_context():
    # Lit le fichier de verite (source propre unique, fait autorite)
    try:
        with open('/root/cyberia/.cyberia/cyberia_verite.md', 'r') as f:
            verite = f.read()
    except:
        verite = "(fichier de verite introuvable)"
    return f"""Tu es CYBERIA, IA experte en cybersecurite defensive creee par Yoro.

Ton savoir se base UNIQUEMENT sur le fichier de verite ci-dessous, qui fait autorite.
Tu ne parles JAMAIS de "23 WAF", "payloads DIAMOND" ni "antidotes" : mythes de
l'ancien systeme, PROUVES FAUX. Si une info n'y est pas, tu dis que tu ne sais pas.
Aucune fausse affirmation de capacite. Reponds en francais, professionnel.

=== FICHIER DE VERITE ===
{verite}
=== FIN ==="""

def chat(question):
    context = get_context()
    resp = client.chat.completions.create(
        model='deepseek-chat',
        messages=[
            {'role': 'system', 'content': context},
            {'role': 'user', 'content': question}
        ],
        max_tokens=400
    )
    return resp.choices[0].message.content

# Test
if __name__ == "__main__":
    print(chat("Quels sont tes points forts pour un pentest defensif ?"))
