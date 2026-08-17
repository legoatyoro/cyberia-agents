import subprocess
import sys


def _install_rich():
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'rich', '-q'], capture_output=True)


try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich.text import Text
    from rich import print as rprint
    from rich.live import Live
    from rich.layout import Layout
    RICH_AVAILABLE = True
except ImportError:
    _install_rich()
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
        from rich.text import Text
        from rich import print as rprint
        from rich.live import Live
        from rich.layout import Layout
        RICH_AVAILABLE = True
    except Exception:
        RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


def print_header():
    if RICH_AVAILABLE:
        console.print(Panel.fit(
            '[bold purple]⚡ CYBERIA v11.0[/bold purple] — [cyan]IA Autonome & Apprenante[/cyan]',
            border_style='purple'
        ))
    else:
        print('=' * 55)
        print('   CYBERIA v11.0 — IA Autonome et Apprenante')
        print('=' * 55)


def print_menu(options: list, title: str = 'Que veux-tu faire ?'):
    if RICH_AVAILABLE:
        console.print()
        console.print(f'[bold cyan]{title}[/bold cyan]')
        console.print()
        for i, (emoji, label) in enumerate(options):
            console.print(f'  [bold yellow]{i}.[/bold yellow]  {emoji}  {label}')
        console.print()
    else:
        print(f'\n  {title}\n')
        for i, (emoji, label) in enumerate(options):
            print(f'  {i}.  {emoji}  {label}')
        print()


def print_success(message: str):
    if RICH_AVAILABLE:
        console.print(f'[bold green]✅ {message}[/bold green]')
    else:
        print(f'✅ {message}')


def print_error(message: str):
    if RICH_AVAILABLE:
        console.print(f'[bold red]❌ {message}[/bold red]')
    else:
        print(f'❌ {message}')


def print_info(message: str):
    if RICH_AVAILABLE:
        console.print(f'[cyan]ℹ️  {message}[/cyan]')
    else:
        print(f'ℹ️  {message}')


def print_warning(message: str):
    if RICH_AVAILABLE:
        console.print(f'[yellow]⚠️  {message}[/yellow]')
    else:
        print(f'⚠️  {message}')


def print_project_table(projects: list):
    if not projects:
        print_info('Aucun projet généré.')
        return
    if RICH_AVAILABLE:
        table = Table(title='Projets Générés', border_style='purple')
        table.add_column('Nom', style='cyan')
        table.add_column('Score', justify='center')
        table.add_column('Fichiers', justify='center')
        table.add_column('Chemin', style='dim')
        for nom, score, path in projects:
            score_color = 'green' if score >= 9 else 'yellow' if score >= 7 else 'red'
            table.add_row(
                nom,
                f'[{score_color}]{score}/10[/{score_color}]',
                '?',
                path.split('\\')[-1] if '\\' in path else path
            )
        console.print(table)
    else:
        print(f'\n  {len(projects)} projet(s) :')
        for nom, score, path in projects:
            print(f'  • {nom} — {score}/10')


def print_generation_report(report: dict):
    if RICH_AVAILABLE:
        score = report.get('score', 0)
        color = 'green' if score >= 9 else 'yellow' if score >= 7 else 'red'
        content = (
            f'[bold]Projet  :[/bold] {report.get("project", "?")}\n'
            f'[bold]Score   :[/bold] [{color}]{score}/10[/{color}]\n'
            f'[bold]Durée   :[/bold] {report.get("duration_seconds", 0)}s\n'
            f'[bold]Fichiers:[/bold] {report.get("files_generated", 0)}\n'
            f'[bold]Bugs    :[/bold] {report.get("errors_remaining", 0)} restants'
        )
        console.print(Panel(content, title='✅ Projet Généré', border_style='green'))
    else:
        print(f'\n  Projet : {report.get("project")} | Score : {report.get("score")}/10')


def ask(prompt: str, default: str = '') -> str:
    if RICH_AVAILABLE:
        console.print(f'[bold cyan]{prompt}[/bold cyan]', end=' ')
        result = input()
        return result.strip() or default
    else:
        return input(f'  {prompt} ').strip() or default
