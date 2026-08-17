def read_project_for_conversation(project_path):
    from pathlib import Path

    path = Path(project_path)
    if not path.exists():
        return None, 'Dossier introuvable'

    EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.json', '.md', '.env.example'}
    SKIP = {'node_modules', '__pycache__', '.git', 'venv', 'env', 'dist', 'build', '.next'}
    MAX_FILES = 15
    MAX_CHARS_PER_FILE = 8000

    files_read = []
    context_parts = [f'PROJET LU : {path.name}', '=' * 50]

    all_files = []
    for f in path.rglob('*'):
        if f.is_file() and f.suffix in EXTENSIONS:
            if not any(skip in f.parts for skip in SKIP):
                all_files.append(f)

    all_files.sort(key=lambda f: f.stat().st_size, reverse=False)
    all_files = all_files[:MAX_FILES]

    for f in all_files:
        try:
            content = f.read_text(encoding='utf-8', errors='ignore')
            if len(content) > MAX_CHARS_PER_FILE:
                content = content[:MAX_CHARS_PER_FILE] + '\n... (tronque)'
            rel_path = f.relative_to(path)
            lines = content.count('\n') + 1
            context_parts.append(f'\n=== {rel_path} ({lines} lignes) ===')
            context_parts.append(content)
            files_read.append(str(rel_path))
        except Exception:
            pass

    context = '\n'.join(context_parts)
    return context, files_read


def smart_input(prompt_text='Toi: '):
    '''
    Capture une entree utilisateur. Si l utilisateur tape /paste,
    bascule en mode collage multi-lignes jusqu a une ligne contenant
    uniquement FIN (ou triple retour a la ligne consecutif).
    Sinon comportement normal d input().
    '''
    first_line = input(prompt_text)

    if first_line.strip() == '/paste':
        print('  [Mode collage actif - colle ton texte puis tape FIN sur une nouvelle ligne et valide]')
        lines = []
        empty_count = 0
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == 'FIN':
                break
            if line.strip() == '':
                empty_count += 1
                if empty_count >= 3:
                    break
            else:
                empty_count = 0
            lines.append(line)
        full_text = chr(10).join(lines)
        print(f'  [Texte capture: {len(full_text)} caracteres, {len(lines)} lignes]')
        return full_text

    return first_line
