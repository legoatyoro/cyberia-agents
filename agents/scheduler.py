import threading, time
from pathlib import Path
from datetime import datetime

_running = False
_thread = None


def start_h24_agents(interval_minutes=30):
    global _running, _thread
    if _running:
        print('  [SCHEDULER] Agents H24 deja actifs')
        return
    _running = True
    Path('.cyberia/scheduler.lock').write_text(datetime.now().isoformat())

    def loop():
        while _running:
            try:
                from agents.cyber_research_agents import run_h24_cycle
                run_h24_cycle()
            except Exception as e:
                print(f'  [SCHEDULER] Erreur cycle: {e}')
            for _ in range(interval_minutes * 60):
                if not _running:
                    break
                time.sleep(1)

    _thread = threading.Thread(target=loop, daemon=True)
    _thread.start()
    print(f'  [SCHEDULER] Agents H24 demarres — cycle toutes les {interval_minutes} min')


def stop_h24_agents():
    global _running
    _running = False
    Path('.cyberia/scheduler.lock').unlink(missing_ok=True)
    print('  [SCHEDULER] Agents H24 arretes')


def get_status():
    lock = Path('.cyberia/scheduler.lock')
    return {'running': _running, 'started_at': lock.read_text() if lock.exists() else None}
