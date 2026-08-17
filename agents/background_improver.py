import time, threading
from pathlib import Path
from datetime import datetime

LOCK_FILE = Path('.cyberia/self_improver.lock')
LOG_FILE = Path('.cyberia/self_improver.log')


def log(msg):
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f'[{datetime.now().strftime("%H:%M:%S")}] {msg}\n')


def is_running():
    if not LOCK_FILE.exists(): return False
    try:
        pid = int(LOCK_FILE.read_text())
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        return False


def start_background(interval_minutes=30, auto_fix=False):
    import os
    if is_running():
        print('  [SELF_IMPROVER] Agent deja actif en arriere-plan')
        return
    LOCK_FILE.parent.mkdir(exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))
    log('Agent demarre')

    def loop():
        while True:
            try:
                from agents.self_improver import run_full_scan
                issues, fixes = run_full_scan(auto_fix=auto_fix)
                log(f'Scan: {len(issues)} problemes, {fixes} fixes')
            except Exception as e:
                log(f'Erreur: {e}')
            time.sleep(interval_minutes * 60)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    print(f'  [SELF_IMPROVER] Agent actif — scan toutes les {interval_minutes} minutes')
    return t


def stop_background():
    if LOCK_FILE.exists():
        LOCK_FILE.unlink()
        log('Agent arrete')
        print('  [SELF_IMPROVER] Agent arrete')


def get_last_report():
    import sqlite3
    from agents.self_improver import DB, get_pending_issues, init_db
    init_db()
    conn = sqlite3.connect(DB)
    last_run = conn.execute('SELECT * FROM improvement_runs ORDER BY id DESC LIMIT 1').fetchone()
    conn.close()
    pending = get_pending_issues()
    return last_run, pending
