from pathlib import Path
from typing import Optional


class ModeSwitcher:
    def __init__(self):
        self.current_project = None
        self.current_project_dir = None
        self.conversation_context = []
        self.session_history = []

    def set_project(self, name, path):
        self.current_project = name
        self.current_project_dir = Path(path) if path else None

    def add_context(self, text):
        self.conversation_context.append(text)
        self.session_history.append(text)

    def get_context(self):
        return '\n'.join(self.conversation_context[-5:])

    def propose_next_actions(self, current_mode, console):
        from rich.panel import Panel

        project_info = f' sur [cyan]{self.current_project}[/cyan]' if self.current_project else ''

        actions = {
            'analyse': [
                ('a', 'Atelier', 'Corriger avec Alex/Sofia/Max'),
                ('t', 'Tests', 'Generer des tests auto'),
                ('c', 'Conseil', 'Demander aux 5 agents'),
                ('v', 'Evolution', 'Ameliorer CYBERIA'),
                ('z', 'Mode A-Z', 'Continuer en mode creation'),
                ('m', 'Menu', 'Revenir au menu principal'),
            ],
            'atelier': [
                ('a', 'Analyser', 'Rapport complet du projet'),
                ('t', 'Tests', 'Generer des tests auto'),
                ('l', 'Lancer', 'Demarrer le projet'),
                ('c', 'Conseil', 'Demander aux 5 agents'),
                ('z', 'Mode A-Z', 'Continuer en mode creation'),
                ('m', 'Menu', 'Revenir au menu principal'),
            ],
            'generation': [
                ('a', 'Analyser', 'Rapport complet du projet'),
                ('w', 'Atelier', 'Ameliorer avec les agents'),
                ('l', 'Lancer', 'Demarrer maintenant'),
                ('t', 'Tests', 'Generer des tests'),
                ('c', 'Conseil', 'Demander aux 5 agents'),
                ('z', 'Mode A-Z', 'Continuer en mode creation'),
                ('m', 'Menu', 'Revenir au menu principal'),
            ],
            'conseil': [
                ('w', 'Atelier', 'Corriger ce que le conseil a trouve'),
                ('a', 'Analyser', 'Rapport detaille'),
                ('t', 'Tests', 'Generer des tests'),
                ('l', 'Lancer', 'Tester en live'),
                ('g', 'Generer', 'Nouveau projet'),
                ('m', 'Menu', 'Revenir au menu principal'),
            ],
            'default': [
                ('a', 'Analyser', 'Analyser un projet'),
                ('w', 'Atelier', 'Mode Atelier'),
                ('c', 'Conseil', 'Conseil Agents'),
                ('t', 'Tests', 'Generer Tests'),
                ('g', 'Generer', 'Nouveau projet'),
                ('m', 'Menu', 'Menu principal'),
            ]
        }

        next_actions = actions.get(current_mode, actions['default'])
        console.print()
        console.print(Panel(
            f'[bold]Que veux-tu faire{project_info} ?[/bold]\n' +
            '  '.join(f'[cyan][{k}][/cyan] {label}' for k, label, _ in next_actions),
            title='[bold yellow]Actions disponibles[/bold yellow]',
            border_style='yellow',
            expand=False
        ))
        for k, label, desc in next_actions:
            console.print(f'  [dim][{k}] {label:12} — {desc}[/dim]')

        try:
            choix = input('\nChoix : ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            choix = 'm'
        return choix, next_actions

    def handle_switch(self, choix, next_actions, project_dir=None):
        target_dir = project_dir or self.current_project_dir
        mapping = {k: label for k, label, _ in next_actions}
        action = mapping.get(choix, '')

        if choix == 'm' or action == 'Menu':
            return 'menu', None
        elif choix == 'a' and 'Analyser' in action:
            return 'analyse', target_dir
        elif choix == 'a' and 'Atelier' in action:
            return 'atelier', target_dir
        elif choix == 'w' or action == 'Atelier':
            return 'atelier', target_dir
        elif choix == 'c' or action == 'Conseil':
            return 'conseil', target_dir
        elif choix == 't' or action == 'Tests':
            return 'tests', target_dir
        elif choix == 'l' or action == 'Lancer':
            return 'lancer', target_dir
        elif choix == 'g' or action == 'Generer':
            return 'generer', None
        elif choix == 'z' or action == 'Mode A-Z':
            return 'az', target_dir
        elif choix == 'v' or action == 'Evolution':
            return 'evolution', None
        return 'menu', None


_switcher = None


def get_switcher():
    global _switcher
    if _switcher is None:
        _switcher = ModeSwitcher()
    return _switcher
