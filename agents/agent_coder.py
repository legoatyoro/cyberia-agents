"""
AgentCoder  CYBERIA IA Autonome v17
Coder autonome : recoit une tache, ecrit le code, execute, lit l erreur, corrige, relance.
Equivalent local de Claude Code.
"""
import os, sys, subprocess, tempfile, time
from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI

MAX_ITERATIONS = 5

client = OpenAI(
    api_key=os.getenv('MIMO_API_KEY'),
    base_url='https://api.xiaomimimo.com/v1'
)

SYSTEM_PROMPT = """Tu es AgentCoder, un developpeur Python autonome expert.
Quand on te donne une tache :
1. Tu ecris du code Python propre et fonctionnel
2. Tu reponds UNIQUEMENT avec le code Python brut, sans markdown, sans explication
3. Le code doit etre executable directement avec python
4. Si on te donne une erreur, tu corriges UNIQUEMENT ce qui pose probleme
5. Tu n utilises que la stdlib Python ou des packages courants (requests, sqlite3, json, os, sys)"""

def call_llm(messages):
    response = client.chat.completions.create(
        model='mimo-v2.5-pro',
        messages=messages,
        max_tokens=2000
    )
    return response.choices[0].message.content.strip()

def clean_code(raw):
    """Enleve les backticks markdown si present"""
    import re
    raw = re.sub(r'^```(?:python)?', '', raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r'```$', '', raw.strip(), flags=re.MULTILINE)
    return raw.strip()

def execute_code(code):
    """Execute le code dans un fichier temp et retourne (success, output, error)"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
        f.write(code)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            timeout=30,
            encoding='utf-8',
            errors='replace'
        )
        os.unlink(tmp_path)
        if result.returncode == 0:
            return True, result.stdout, None
        else:
            return False, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        os.unlink(tmp_path)
        return False, '', 'TIMEOUT: code depasse 30 secondes'
    except Exception as e:
        return False, '', str(e)

def run_task(task_description):
    print(f"\n{'='*60}")
    print(f"[AgentCoder] Tache: {task_description}")
    print(f"{'='*60}")

    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': f"Tache: {task_description}\n\nEcris le code Python pour accomplir cette tache."}
    ]

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n[ITER {iteration}/{MAX_ITERATIONS}] Generation du code...")
        raw_code = call_llm(messages)
        code = clean_code(raw_code)

        print(f"[ITER {iteration}] Code genere ({len(code)} chars)")
        print(f"--- DEBUT CODE ---")
        print(code[:300] + ('...' if len(code) > 300 else ''))
        print(f"--- FIN CODE ---")

        print(f"[ITER {iteration}] Execution...")
        success, output, error = execute_code(code)

        if success:
            print(f"\n[SUCCESS] Code fonctionne apres {iteration} iteration(s)")
            print(f"[OUTPUT]\n{output[:500]}")
            return {'success': True, 'code': code, 'output': output, 'iterations': iteration}
        else:
            print(f"[ERREUR] {error[:200]}")
            if iteration < MAX_ITERATIONS:
                messages.append({'role': 'assistant', 'content': raw_code})
                messages.append({'role': 'user', 'content': f"Erreur d execution:\n{error}\n\nCorrige le code. Reponds UNIQUEMENT avec le code Python corrige, sans explication."})
            else:
                print(f"[ECHEC] {MAX_ITERATIONS} iterations atteintes")
                return {'success': False, 'code': code, 'error': error, 'iterations': iteration}

    return {'success': False, 'error': 'Max iterations', 'iterations': MAX_ITERATIONS}

if __name__ == '__main__':
    # Tests de demonstration
    taches = [
        "Lis la liste des fichiers .py dans le repertoire courant et affiche leur taille en Ko",
        "Connecte toi a SQLite en memoire, cree une table 'agents' avec id/nom/statut, insere 3 agents CYBERIA et affiche les resultats",
        "Genere 5 payloads XSS simples et calcule leur score de dangerosité sur une echelle 1-10"
    ]

    for tache in taches:
        result = run_task(tache)
        print(f"\nResultat: {'OK' if result['success'] else 'ECHEC'} en {result['iterations']} iteration(s)")
        print("-" * 60)
        time.sleep(2)

