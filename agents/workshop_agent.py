from core.multi_model_router import get_router
from core.file_analyzer import FileAnalyzer
from pathlib import Path
import json


class WorkshopAgent:
    def __init__(self, name: str, specialty: str, personality: str):
        self.name = name
        self.specialty = specialty
        self.personality = personality
        self.router = get_router()

    def respond(self, context: str, user_message: str, project_info: dict) -> str:
        prompt = f'''Tu es {self.name}, expert en {self.specialty}.
Personnalité : {self.personality}
Projet analysé : {project_info.get('name', 'inconnu')} ({project_info.get('stack', '')})
Contexte conversation : {context[-1000:] if len(context) > 1000 else context}

L utilisateur dit : {user_message}

Réponds en tant que {self.name} avec ton expertise en {self.specialty}.
Sois concis (3-5 phrases max), direct et pratique.
Propose des améliorations concrètes et actionnables.
Tu peux être en accord ou en désaccord avec les autres agents.'''
        return self.router.call(prompt, task_type='analysis', temperature=0.6)

    def propose_fix(self, filepath: Path, issue: str, context: str) -> dict:
        content = filepath.read_text(encoding='utf-8', errors='ignore')
        prompt = f'''Tu es {self.name}, expert en {self.specialty}.
Voici un fichier à corriger :

FICHIER : {filepath.name}
PROBLÈME : {issue}
CODE ACTUEL :
{content[:4000]}

Génère le fichier corrigé complet. AUCUN markdown, code Python/JS pur uniquement.
Ne change que ce qui est nécessaire pour corriger le problème.'''
        fixed = self.router.call(prompt, task_type='fix', temperature=0.15)
        from cyberia_sanitizer import strip_markdown_artifacts
        fixed = strip_markdown_artifacts(fixed)
        return {'file': str(filepath), 'original': content, 'fixed': fixed, 'agent': self.name}

    def apply_fix(self, fix: dict) -> bool:
        import ast, shutil
        from datetime import datetime
        filepath = Path(fix['file'])
        backup = filepath.with_suffix(filepath.suffix + f'.{datetime.now().strftime("%H%M%S")}.bak')
        try:
            shutil.copy2(filepath, backup)
            if filepath.suffix == '.py':
                ast.parse(fix['fixed'])
            filepath.write_text(fix['fixed'], encoding='utf-8')
            return True
        except Exception:
            if backup.exists():
                shutil.copy2(backup, filepath)
            return False

    def find_files_to_fix(self, project_dir: Path, issue_type: str) -> list:
        import ast as ast_module
        broken = []
        for py_file in project_dir.rglob('*.py'):
            if 'node_modules' in str(py_file) or '__pycache__' in str(py_file):
                continue
            try:
                ast_module.parse(py_file.read_text(encoding='utf-8', errors='ignore'))
            except SyntaxError as e:
                broken.append({'file': py_file, 'error': str(e)})
        return broken[:5]

    def identify_target_file(self, project_dir: Path, context: str, project_info: dict) -> Path | None:
        py_files = [
            str(f.relative_to(project_dir))
            for f in project_dir.rglob('*.py')
            if 'node_modules' not in str(f) and '__pycache__' not in str(f)
        ][:20]
        prompt = f'''Tu es {self.name}, expert en {self.specialty}.
Fichiers Python du projet {project_info.get("name")} :
{chr(10).join(py_files)}

Contexte : {context[-500:]}

Quel fichier est le plus problématique selon ton expertise en {self.specialty} ?
Réponds UNIQUEMENT avec le chemin relatif exact du fichier (ex: main.py ou core/utils.py).
Aucune explication.'''
        raw = self.router.call(prompt, task_type='analysis', temperature=0.2).strip()
        candidate = project_dir / raw.strip().strip('`').strip('"')
        if candidate.exists():
            return candidate
        for f in project_dir.rglob('*.py'):
            if 'node_modules' not in str(f) and '__pycache__' not in str(f):
                if f.name == Path(raw).name:
                    return f
        return None


class ValidatorAgent:
    def __init__(self):
        self.router = get_router()
        self.name = 'VALIDATOR'

    def validate_fix(self, original_code: str, fixed_code: str, proposal: str) -> dict:
        import ast
        try:
            ast.parse(fixed_code)
        except SyntaxError as e:
            return {'approved': False, 'reason': f'Syntaxe invalide ligne {e.lineno}', 'risk': 'high'}

        if len(fixed_code.splitlines()) < len(original_code.splitlines()) * 0.5:
            return {'approved': False, 'reason': 'Code trop court - probablement tronqué', 'risk': 'high'}

        original_funcs = set(
            l.strip().split('(')[0].replace('def ', '').replace('async ', '')
            for l in original_code.splitlines()
            if l.strip().startswith('def ') or l.strip().startswith('async def ')
        )
        fixed_funcs = set(
            l.strip().split('(')[0].replace('def ', '').replace('async ', '')
            for l in fixed_code.splitlines()
            if l.strip().startswith('def ') or l.strip().startswith('async def ')
        )
        missing = original_funcs - fixed_funcs
        if missing:
            return {'approved': False, 'reason': f'Fonctions supprimées : {missing}', 'risk': 'high'}

        prompt = f'''Valide cette correction de code Python en 1 phrase.
PROPOSITION : {proposal[:200]}
CODE ORIGINAL ({len(original_code.splitlines())} lignes) → CORRIGÉ ({len(fixed_code.splitlines())} lignes)
Réponds UNIQUEMENT : APPROUVÉ|REJETÉ: raison courte'''
        response = self.router.call(prompt, task_type='analysis', temperature=0.1)
        approved = response.strip().upper().startswith('APPROUVÉ')
        reason = response.split(':', 1)[-1].strip() if ':' in response else response
        return {'approved': approved, 'reason': reason, 'risk': 'low' if approved else 'medium'}


WORKSHOP_AGENTS = [
    WorkshopAgent('Alex', 'architecture et performance', 'Direct, analytique, orienté performance'),
    WorkshopAgent('Sofia', 'UX et interface utilisateur', 'Créative, centrée utilisateur, empathique'),
    WorkshopAgent('Max', 'sécurité et bonnes pratiques', 'Rigoureux, prudent, orienté qualité'),
]

AGENT_COLOR = {'Alex': 'cyan', 'Sofia': 'magenta', 'Max': 'yellow'}


def _agent_color(name: str) -> str:
    return AGENT_COLOR.get(name, 'white')


def _simple_diff(original: str, fixed: str) -> str:
    orig_lines = original.splitlines()
    fix_lines = fixed.splitlines()
    shown = 0
    parts = []
    for o, f in zip(orig_lines, fix_lines):
        if o != f:
            parts.append(f'[red]- {o[:90]}[/red]')
            parts.append(f'[green]+ {f[:90]}[/green]')
            shown += 1
            if shown >= 8:
                parts.append('[dim]  … (diff tronqué)[/dim]')
                break
    if len(fix_lines) > len(orig_lines):
        for line in fix_lines[len(orig_lines):len(orig_lines) + 4]:
            parts.append(f'[green]+ {line[:90]}[/green]')
    return '\n'.join(parts) if parts else '[dim](aucun changement détecté)[/dim]'


def run_workshop(project_dir: Path, project_name: str):
    import uuid
    from rich.console import Console
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.prompt import Prompt
    from rich import box
    from rich.table import Table

    console = Console()
    session_id = f'workshop_{project_name}_{uuid.uuid4().hex[:6]}'
    session_transcript = []

    console.print()
    console.print(Panel(
        f'[bold purple]🔬 Mode Atelier — {project_name}[/bold purple]\n'
        f'[dim]Alex (Architecture) · Sofia (UX) · Max (Sécurité)[/dim]\n'
        f'[dim]Discute avec tes agents pour améliorer le projet.[/dim]\n\n'
        f'[dim]Commandes :[/dim] [cyan]analyse[/cyan] [dim]·[/dim] [cyan]corrige[/cyan] [dim]·[/dim] '
        f'[cyan]syntax[/cyan] [dim]·[/dim] [cyan]todo[/cyan] [dim]·[/dim] [cyan]auto[/cyan] [dim]·[/dim] '
        f'[cyan]applique[/cyan] [dim]·[/dim] [cyan]quitter[/cyan]',
        border_style='purple', padding=(1, 2)
    ))

    analyzer = FileAnalyzer()
    project_info = {'name': project_name, 'stack': 'Python', 'path': str(project_dir)}
    context = f'Projet : {project_name}\n'
    suggestions_pending = []

    try:
        result = analyzer.analyze_project(project_dir)
        files = result.get('files_analyzed', 0)
        initial_analysis = f'{files} fichiers analysés.'
        for r in result.get('results', [])[:2]:
            analysis = r.get('analysis') or r.get('synthesis', '')
            initial_analysis += ' ' + analysis[:300]
        context += f'Analyse initiale : {initial_analysis}\n'
    except Exception as e:
        context += f'Projet chargé (analyse rapide : {e})\n'

    try:
        from core.learning_engine import get_workshop_history, save_workshop_session
        history = get_workshop_history(project_name)
        if history:
            context += f'Historique sessions précédentes ({len(history)}) : '
            for h in history[:2]:
                context += h['discussion'][:200] + ' | '
    except Exception:
        pass

    console.print()
    console.print(Rule('[dim]Démarrage de l\'atelier[/dim]'))

    for agent in WORKSHOP_AGENTS:
        intro = agent.respond(context, 'Présente-toi et donne ta première impression du projet en 2 phrases.', project_info)
        console.print()
        color = _agent_color(agent.name)
        console.print(Panel(intro, title=f'[bold {color}]{agent.name}[/bold {color}]', border_style=color, padding=(0, 1)))
        context += f'\n{agent.name}: {intro}'

    console.print()
    console.print('  [dim]Astuce : pour coller un texte long (CDC, document), tape /paste puis colle, puis FIN sur une nouvelle ligne[/dim]')
    console.print()

    from core.input_utils import smart_input
    while True:
        console.print()
        try:
            user_input = smart_input('Toi: ')
        except (KeyboardInterrupt, EOFError):
            break
        if not user_input:
            continue
        session_transcript.append(f'user: {user_input}')
        if user_input.lower() in ['changer', 'switch']:
            console.print()
            console.print('[bold cyan]Changer de mode avec ce projet :[/bold cyan]')
            console.print('  [cyan]1.[/cyan] Mode Analyse')
            console.print('  [cyan]2.[/cyan] Mode Amelioration')
            console.print('  [cyan]3.[/cyan] Continuer l\'atelier')
            choix = Prompt.ask('[cyan]Choix[/cyan]', default='3').strip()
            if choix == '1':
                console.print(Rule('[dim]Analyse[/dim]'))
                try:
                    result_a = analyzer.analyze_project(project_dir)
                    console.print(f'  [green]✅[/green] {result_a.get("files_analyzed", 0)} fichiers analysés')
                    for r in result_a.get('results', [])[:3]:
                        console.print(f'\n  [cyan]📄 {Path(r["file"]).name}[/cyan]')
                        analysis = r.get('analysis') or r.get('synthesis', '')
                        for line in analysis.split('\n')[:5]:
                            if line.strip(): console.print(f'     [dim]{line[:80]}[/dim]')
                except Exception as e:
                    console.print(f'[red]❌ {e}[/red]')
            elif choix == '2':
                console.print('[cyan]Amélioration en cours...[/cyan]')
                try:
                    from core.improvement_loop import ImprovementLoop
                    report = ImprovementLoop().run(project_dir)
                    gain = report['final_score'] - report['initial_score']
                    color = 'green' if gain > 0 else 'yellow'
                    console.print(f'  Score : [bold]{report["initial_score"]}[/bold] → [bold {color}]{report["final_score"]}[/bold {color}]/10 (+{gain})')
                except Exception as e:
                    console.print(f'[red]❌ {e}[/red]')
            continue
        if user_input.lower() in ['quitter', 'exit', 'menu']:
            try:
                from core.learning_engine import save_workshop_session
                save_workshop_session(project_name, 'all_agents', context[-2000:], suggestions_pending)
                console.print('[dim]Session sauvegardée dans la mémoire CYBERIA.[/dim]')
            except Exception:
                pass
            from core.memory_hub import extract_session_memories
            extract_session_memories(session_id, '\n'.join(session_transcript), mode='atelier')
            break

        context += f'\nUtilisateur: {user_input}'

        # ── analyse ──────────────────────────────────────────────────
        if user_input.lower() == 'analyse':
            console.print(Rule('[dim]Bilan des agents[/dim]'))
            for agent in WORKSHOP_AGENTS:
                response = agent.respond(context, 'Fais un bilan : quels sont les 2 points les plus importants à améliorer ?', project_info)
                color = _agent_color(agent.name)
                console.print()
                console.print(Panel(response, title=f'[bold {color}]{agent.name}[/bold {color}]', border_style=color, padding=(0, 1)))
                context += f'\n{agent.name}: {response}'
                suggestions_pending.append({'agent': agent.name, 'suggestion': response})

        # ── corrige ──────────────────────────────────────────────────
        elif user_input.lower() == 'corrige':
            console.print(Rule('[dim]Identification et correction[/dim]'))
            for agent in WORKSHOP_AGENTS:
                color = _agent_color(agent.name)
                console.print(f'\n  [bold {color}]{agent.name}[/bold {color}] identifie un fichier...')
                target = agent.identify_target_file(project_dir, context, project_info)
                if not target:
                    console.print(f'  [dim]{agent.name} : aucun fichier identifié[/dim]')
                    continue
                issue_response = agent.respond(
                    context,
                    f'Quel est le problème principal dans {target.name} selon ton expertise ? 1 phrase.',
                    project_info
                )
                console.print(f'  [dim]Fichier : {target.relative_to(project_dir)} — {issue_response[:100]}[/dim]')
                fix = agent.propose_fix(target, issue_response, context)
                diff_text = _simple_diff(fix['original'], fix['fixed'])
                console.print()
                console.print(Panel(
                    diff_text,
                    title=f'[bold {color}]Diff proposé par {agent.name} — {target.name}[/bold {color}]',
                    border_style=color, padding=(0, 1)
                ))
                confirm = Prompt.ask(
                    f'[{color}]Appliquer la correction de {agent.name} sur {target.name} ?[/{color}] (o/n)'
                ).lower()
                if confirm == 'o':
                    ok = agent.apply_fix(fix)
                    if ok:
                        console.print(f'  [green]✅ Correction appliquée — backup .bak créé[/green]')
                        context += f'\n{agent.name}: correction appliquée sur {target.name}'
                        from core.memory_hub import save_correction
                        save_correction(session_id, f'{agent.name} a corrige {target.name}: {fix.get("explanation", issue_response)[:150]}')
                        try:
                            from core.error_learner import learn_from_error
                            from agents.language_experts import detect_expert
                            detected = detect_expert(project_dir)
                            lang = detected.language.split('/')[0].lower()
                            learn_from_error(issue_response[:300], fix.get('fixed', '')[:300], stack=lang, worked=True)
                        except Exception:
                            pass
                        try:
                            from core.enrichment import save_fix_pattern, log_improvement
                            save_fix_pattern(
                                component=target.name,
                                problem=f'{agent.name}: {issue_response[:100]}',
                                solution=fix.get('explanation', 'correction appliquee')[:200],
                                tags=[agent.name, target.suffix, project_name[:20]]
                            )
                            log_improvement(agent=agent.name, task=f'Fix {target.name}', component=project_name, success=True, user_feedback=4)
                        except Exception:
                            pass
                    else:
                        console.print(f'  [red]❌ Correction invalide — fichier original restauré[/red]')
                else:
                    console.print(f'  [dim]Ignoré.[/dim]')

        # ── syntax ───────────────────────────────────────────────────
        elif user_input.lower() == 'syntax':
            console.print(Rule('[dim]Détection des erreurs de syntaxe Python[/dim]'))
            broken = WORKSHOP_AGENTS[0].find_files_to_fix(project_dir, 'syntax')
            if not broken:
                console.print('  [green]✅ Aucune erreur de syntaxe trouvée.[/green]')
            else:
                table = Table(box=box.SIMPLE, border_style='dim', header_style='bold red')
                table.add_column('Fichier', style='cyan')
                table.add_column('Erreur', style='red')
                for item in broken:
                    rel = str(item['file'].relative_to(project_dir))
                    table.add_row(rel, item['error'][:80])
                console.print()
                console.print(table)
                console.print()
                confirm = Prompt.ask(f'[yellow]Corriger automatiquement ces {len(broken)} fichier(s) ?[/yellow] (o/n)').lower()
                if confirm == 'o':
                    for item in broken:
                        agent = WORKSHOP_AGENTS[2]  # Max, expert qualité
                        fix = agent.propose_fix(item['file'], f'Erreur de syntaxe : {item["error"]}', context)
                        ok = agent.apply_fix(fix)
                        rel = str(item['file'].relative_to(project_dir))
                        status = '[green]✅[/green]' if ok else '[red]❌[/red]'
                        console.print(f'  {status} {rel}')

        # ── todo ─────────────────────────────────────────────────────
        elif user_input.lower() == 'todo':
            console.print(Rule('[dim]Tâches prioritaires[/dim]'))
            todos = []
            for agent in WORKSHOP_AGENTS:
                color = _agent_color(agent.name)
                task = agent.respond(
                    context,
                    'Donne UNE seule tâche prioritaire à faire sur ce projet. Format : TÂCHE: <description courte>. FICHIER: <nom du fichier cible>.',
                    project_info
                )
                console.print()
                console.print(Panel(task, title=f'[bold {color}]{agent.name}[/bold {color}]', border_style=color, padding=(0, 1)))
                context += f'\n{agent.name}: {task}'
                todos.append({'agent': agent, 'task': task})

            console.print()
            for i, t in enumerate(todos, 1):
                console.print(f'  [bold yellow]{i}.[/bold yellow] [{_agent_color(t["agent"].name)}]{t["agent"].name}[/{_agent_color(t["agent"].name)}] : {t["task"][:80]}')

            console.print()
            choix = Prompt.ask('[cyan]Quelle tâche appliquer ?[/cyan] [dim](numéro, ou entrée pour passer)[/dim]', default='')
            if choix.strip():
                try:
                    idx = int(choix.strip()) - 1
                    if 0 <= idx < len(todos):
                        selected = todos[idx]
                        agent = selected['agent']
                        color = _agent_color(agent.name)
                        console.print(f'\n  [bold {color}]{agent.name}[/bold {color}] génère le code...')
                        target = agent.identify_target_file(project_dir, context, project_info)
                        if target:
                            fix = agent.propose_fix(target, selected['task'], context)
                            diff_text = _simple_diff(fix['original'], fix['fixed'])
                            console.print()
                            console.print(Panel(diff_text, title=f'[bold {color}]Changements — {target.name}[/bold {color}]', border_style=color, padding=(0, 1)))
                            confirm = Prompt.ask(f'[{color}]Appliquer ?[/{color}] (o/n)').lower()
                            if confirm == 'o':
                                ok = agent.apply_fix(fix)
                                console.print(f'  [{"green]✅ Appliqué" if ok else "red]❌ Échec"}] — backup .bak créé[/{"green" if ok else "red"}]')
                        else:
                            console.print(f'  [yellow]⚠️ Fichier cible introuvable.[/yellow]')
                except (ValueError, IndexError):
                    console.print('  [dim]Choix ignoré.[/dim]')

        # ── auto ─────────────────────────────────────────────────────
        elif user_input.lower() == 'auto':
            console.print()
            console.print(Rule('[cyan]Mode Automatique — VALIDATOR actif[/cyan]'))
            console.print('  [dim]🤖 Mode automatique — le VALIDATOR vérifie chaque correction avant application[/dim]')
            validator = ValidatorAgent()
            approved_count = 0
            rejected_count = 0

            for agent in WORKSHOP_AGENTS:
                color = _agent_color(agent.name)
                console.print(f'\n  [bold {color}]{agent.name}[/bold {color}] identifie et corrige...')
                try:
                    target = agent.identify_target_file(project_dir, context, project_info)
                    if not target or not target.exists():
                        console.print(f'    [dim]Aucun fichier identifié.[/dim]')
                        continue
                    original = target.read_text(encoding='utf-8', errors='ignore')
                    fix = agent.propose_fix(target, f'Améliorer selon expertise {agent.specialty}', context)
                    if not fix.get('fixed') or len(fix['fixed']) < 50:
                        console.print(f'    [yellow]⚠️ Fix vide ou trop court — ignoré[/yellow]')
                        continue
                    validation = validator.validate_fix(original, fix['fixed'], f'Expertise {agent.specialty}')
                    if validation['approved']:
                        ok = agent.apply_fix(fix)
                        if ok:
                            approved_count += 1
                            console.print(f'    [green]✅ [VALIDATOR] Approuvé et appliqué : {validation["reason"][:60]}[/green]')
                            context += f'\n{agent.name} a corrigé {target.name} : {validation["reason"]}'
                            suggestions_pending.append({'agent': agent.name, 'file': target.name, 'validated': True})
                        else:
                            console.print(f'    [red]❌ Application échouée malgré validation[/red]')
                    else:
                        rejected_count += 1
                        console.print(f'    [red]❌ [VALIDATOR] Rejeté ({validation["risk"]}) : {validation["reason"][:60]}[/red]')
                except Exception as e:
                    console.print(f'    [dim]Erreur {agent.name} : {e}[/dim]')

            console.print()
            console.print(Panel(
                f'[green]✅ {approved_count} correction(s) approuvées et appliquées[/green]\n'
                f'[red]❌ {rejected_count} correction(s) rejetées par le VALIDATOR[/red]',
                title='Bilan Mode Automatique', border_style='cyan'
            ))

        # ── applique ─────────────────────────────────────────────────
        elif user_input.lower().startswith('applique'):
            console.print()
            if Prompt.ask('[yellow]Lancer l\'amélioration automatique sur ce projet ?[/yellow] (o/n)').lower() == 'o':
                from core.improvement_loop import ImprovementLoop
                console.print('[cyan]Amélioration en cours...[/cyan]')
                try:
                    report = ImprovementLoop().run(project_dir)
                    gain = report['final_score'] - report['initial_score']
                    console.print(f'[green]✅ Score : {report["initial_score"]} → {report["final_score"]}/10 (+{gain})[/green]')
                except Exception as e:
                    console.print(f'[red]❌ {e}[/red]')

        # ── conseil ──────────────────────────────────────────────────
        elif user_input.lower() == 'conseil':
            console.print(Rule('[dim]Conseil d\'Agents[/dim]'))
            try:
                from core.agent_council import AgentCouncil
                council = AgentCouncil()
                opinions, consensus = council.collaborative_review(project_dir)
                for key, data in opinions.items():
                    agent_info = data['agent']
                    console.print()
                    console.print(Panel(
                        data['opinion'],
                        title=f'{agent_info["emoji"]} {agent_info["name"]}',
                        border_style='magenta', padding=(0, 1)
                    ))
                console.print()
                console.print(Panel(consensus, title='[bold green]🤝 CONSENSUS DU CONSEIL[/bold green]', border_style='green'))
                context += f'\nConseil: {consensus[:300]}'
            except Exception as e:
                console.print(f'[red]❌ Erreur conseil : {e}[/red]')

        # ── réponse libre ─────────────────────────────────────────────
        else:
            for agent in WORKSHOP_AGENTS:
                response = agent.respond(context, user_input, project_info)
                color = _agent_color(agent.name)
                console.print()
                console.print(Panel(response, title=f'[bold {color}]{agent.name}[/bold {color}]', border_style=color, padding=(0, 1)))
                context += f'\n{agent.name}: {response}'
