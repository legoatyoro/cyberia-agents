from core.memory_engine import get_stats_summary, suggest_improvements, get_preference


def analyze_and_suggest(project_type: str, last_score: float) -> list:
    suggestions = []

    improvements = suggest_improvements(project_type)
    if improvements:
        patterns = [f'- {i["error"]} → {i["fix"][:50]}' for i in improvements[:3]]
        suggestions.append({
            'type': 'learned_fix',
            'message': f'J\'ai appris {len(improvements)} fix(es) pour les projets {project_type}. Je les appliquerai automatiquement.',
            'details': patterns
        })

    if last_score < 8:
        suggestions.append({
            'type': 'quality',
            'message': 'Score inférieur à 8/10. Veux-tu que je relance l\'amélioration automatique ?',
            'action': 'improve'
        })

    stats = get_stats_summary()
    if stats['total_projects'] > 0 and stats['total_projects'] % 5 == 0:
        suggestions.append({
            'type': 'milestone',
            'message': (
                f'🎯 {stats["total_projects"]} projets générés ! '
                f'Score moyen : {stats["avg_score"]}/10. '
                f'{stats["known_fix_patterns"]} patterns d\'erreurs mémorisés.'
            )
        })

    return suggestions


def display_suggestions(suggestions: list):
    from core.smart_cli import print_info, print_warning
    if not suggestions:
        return
    print()
    print_info('💡 Suggestions basées sur ton historique :')
    for s in suggestions:
        if s['type'] == 'learned_fix':
            print_info(s['message'])
        elif s['type'] == 'quality':
            print_warning(s['message'])
        elif s['type'] == 'milestone':
            print_info(s['message'])
    print()
