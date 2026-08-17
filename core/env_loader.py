import os
from pathlib import Path


def load_env():
    env_path = Path('.env')
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)
    keys = {
        'DEEPSEEK_API_KEY': bool(os.getenv('DEEPSEEK_API_KEY')),
        'GROQ_API_KEY': bool(os.getenv('GROQ_API_KEY')),
        'MISTRAL_API_KEY': bool(os.getenv('MISTRAL_API_KEY')),
    }
    active = [k for k, v in keys.items() if v]
    missing = [k for k, v in keys.items() if not v]
    print(f'  [ENV] APIs actives: {active}')
    if missing:
        print(f'  [ENV] Manquantes: {missing} -> fallback DeepSeek')
    try:
        import urllib.request
        urllib.request.urlopen('http://localhost:11434', timeout=1)
        print('  [ENV] Ollama: ACTIF')
    except Exception:
        print('  [ENV] Ollama: INACTIF')
    return keys
