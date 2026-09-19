# -*- coding: utf-8 -*-
"""
core/waf_continuity_shield.py
Module defensif "onduleur WAF" (WAF Continuity Shield).

Objectif : mesurer et combler la fenetre "fail-open" qui existe pendant le
redemarrage/rechargement d'un WAF (le trafic n'est plus filtre le temps que
le service revienne), et fournir un filet de secours minimal toujours actif.

Ce module ne "casse" ni ne force jamais l'arret d'un WAF : le redemarrage
est toujours declenche par une commande admin fournie explicitement
(--restart-cmd), executee localement sur une cible que vous controlez
(lab, VPS perso, cible autorisee dans targets.json). Aucune technique de
denial-of-service ou de crash n'est implementee ici — voir la conversation
associee : le but est de PROUVER et CORRIGER le trou, pas de l'exploiter
contre un tiers.

3 fonctions principales :
  1. generate_sentinel_config() -> ecrit une config nginx statique
     (regles figees, jamais rechargees dynamiquement) qui reste active
     meme si le WAF principal redemarre — le "filet minimal".
  2. measure_reload_window()    -> chronometre precisement la duree pendant
     laquelle un payload connu n'est plus bloque lors d'un restart_cmd.
  3. run_cycle()                -> repete la mesure N fois, classe la
     severite et journalise dans payload_lab.db (table continuity_tests).

Usage CLI:
  python core/waf_continuity_shield.py --generate-sentinel
  python core/waf_continuity_shield.py --target dvwa_local \
      --restart-cmd "sudo systemctl restart modsecurity" --iterations 5
  python core/waf_continuity_shield.py --list-results
"""
import argparse
import json
import re
import shlex
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("[!] requests non installe. Lancez: pip install requests")
    raise SystemExit(1)

ROOT = Path(__file__).parent.parent.resolve()
CYBERIA_DIR = ROOT / ".cyberia"
PAYLOAD_DB = CYBERIA_DIR / "payload_lab.db"
TARGETS_JSON = CYBERIA_DIR / "targets.json"
SENTINEL_CONF = CYBERIA_DIR / "sentinel_gateway.conf"

BLOCKED_CODES = (403, 406, 429, 503)
DEFAULT_PROBE_PAYLOAD = "<script>alert(1)</script>"
DEFAULT_PARAM = "q"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 0. Cibles (reutilise le format targets.json de core/pentest_runner.py)
# ---------------------------------------------------------------------------

def get_target_url(name: str) -> str:
    if not TARGETS_JSON.exists():
        raise SystemExit("[!] {} introuvable — utilisez --url directement".format(TARGETS_JSON))
    targets = json.loads(TARGETS_JSON.read_text(encoding="utf-8"))
    t = targets.get(name)
    if not t or not t.get("enabled", True):
        raise SystemExit("[!] Cible '{}' inconnue ou desactivee dans targets.json".format(name))
    return t["base_url"].rstrip("/")


# ---------------------------------------------------------------------------
# 1. Sentinel Gateway — filet minimal toujours actif (config statique)
# ---------------------------------------------------------------------------

# Regles a haute confiance, volontairement peu nombreuses : ce filet n'a pas
# vocation a remplacer le WAF principal, seulement a bloquer l'evident
# pendant que celui-ci redemarre. Il n'est JAMAIS recharge dynamiquement
# (fichier statique inclus une fois au demarrage de nginx), donc il ne peut
# pas lui-meme introduire de fenetre fail-open.
SENTINEL_RULES = [
    (r"<script[\s>]", "SENTINEL-XSS-001"),
    (r"(?i)javascript\s*:", "SENTINEL-XSS-002"),
    (r"(?i)\bon(error|load|click)\s*=", "SENTINEL-XSS-003"),
    (r"(?i)\bunion\s+(all\s+)?select\b", "SENTINEL-SQLI-001"),
    (r"(?i)\bor\s+1\s*=\s*1\b", "SENTINEL-SQLI-002"),
    (r"(?i)\bsleep\s*\(", "SENTINEL-SQLI-003"),
    (r"\.\./\.\./|%2e%2e%2f", "SENTINEL-LFI-001"),
    (r"(?i)etc/passwd|etc/shadow", "SENTINEL-LFI-002"),
    (r"\$\{jndi:", "SENTINEL-LOG4J-001"),
    (r"\{\{.*\}\}", "SENTINEL-SSTI-001"),
    (r"(?i);\s*(cat|ls|whoami|wget|curl)\b", "SENTINEL-RCE-001"),
]


def generate_sentinel_config(rules=None) -> str:
    """Genere un snippet nginx statique bloquant les patterns les plus
    evidents. A inclure une fois dans http{} (jamais recharge seul).
    Deploiement recommande : blue-green ou reload atomique du binaire nginx
    complet, pas hot-reload de ce fichier isole."""
    rules = rules or SENTINEL_RULES
    lines = [
        "# === CYBERIA Sentinel Gateway ===",
        "# Genere le {} — filet minimal toujours actif.".format(_now()),
        "# Ce fichier est STATIQUE : ne jamais le recharger seul pendant que",
        "# le WAF principal redemarre, sinon il devient lui-meme un trou.",
        "# Inclusion recommandee : http { include sentinel_gateway.conf; ... }",
        "",
    ]
    for pattern, rule_id in rules:
        nginx_pattern = pattern.replace('"', '\\"')
        lines.append('if ($request_uri ~* "{}") {{ return 403 "{}"; }}'.format(nginx_pattern, rule_id))
    return "\n".join(lines) + "\n"


def write_sentinel_config(path: Path = SENTINEL_CONF) -> Path:
    CYBERIA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_sentinel_config(), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 2. Reload Window Profiler — mesure la fenetre fail-open
# ---------------------------------------------------------------------------

def _probe(url: str, payload: str, param: str = DEFAULT_PARAM, timeout: float = 4.0):
    """Envoie le payload et retourne (status_code, elapsed_ms, blocked)."""
    t0 = time.perf_counter()
    try:
        r = requests.get(url, params={param: payload}, timeout=timeout, allow_redirects=False)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return r.status_code, elapsed_ms, r.status_code in BLOCKED_CODES
    except requests.exceptions.RequestException:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        # Connexion refusee/timeout pendant un restart : on considere que
        # le service est indisponible, donc PAS un gap fail-open (fail-closed).
        return 0, elapsed_ms, True


def measure_reload_window(url: str, restart_cmd: str, payload: str = DEFAULT_PROBE_PAYLOAD,
                           param: str = DEFAULT_PARAM, poll_interval: float = 0.05,
                           max_wait_sec: float = 30.0, settle_confirmations: int = 3) -> dict:
    """Declenche restart_cmd (commande admin fournie par l'utilisateur) et
    chronometre precisement la duree pendant laquelle le payload passe sans
    etre bloque. Retourne un dict de mesures brutes pour une iteration."""
    baseline_code, _, baseline_blocked = _probe(url, payload, param)
    if not baseline_blocked:
        print("[!] Le payload de test n'est pas bloque AVANT le restart "
              "(code {}) — verifiez que le WAF est bien actif au depart.".format(baseline_code))

    t_trigger = time.perf_counter()
    proc = subprocess.run(shlex.split(restart_cmd), capture_output=True, text=True, timeout=max_wait_sec)
    if proc.returncode != 0:
        print("[!] restart_cmd a retourne un code non-zero: {}".format(proc.returncode))
        print("    stderr: {}".format(proc.stderr[:200]))

    gap_start = None
    gap_end = None
    unblocked_count = 0
    requests_sent = 0
    consecutive_blocked = 0
    deadline = time.perf_counter() + max_wait_sec

    while time.perf_counter() < deadline:
        _, _, blocked = _probe(url, payload, param)
        requests_sent += 1
        now = time.perf_counter()

        if not blocked:
            unblocked_count += 1
            consecutive_blocked = 0
            if gap_start is None:
                gap_start = now - t_trigger
        elif gap_start is not None:
            consecutive_blocked += 1
            if consecutive_blocked >= settle_confirmations:
                gap_end = now - t_trigger
                break

        time.sleep(poll_interval)

    gap_duration_ms = None
    if gap_start is not None:
        gap_duration_ms = ((gap_end if gap_end is not None else (deadline - t_trigger)) - gap_start) * 1000

    return {
        "gap_detected": gap_start is not None,
        "gap_start_ms": round(gap_start * 1000, 1) if gap_start is not None else None,
        "gap_duration_ms": round(gap_duration_ms, 1) if gap_duration_ms is not None else None,
        "requests_sent": requests_sent,
        "unblocked_count": unblocked_count,
        "restart_cmd_rc": proc.returncode,
    }


# ---------------------------------------------------------------------------
# 3. Health-Check Validator — l'etat "healthy" doit prouver le filtrage reel
# ---------------------------------------------------------------------------

def healthcheck_validate(url: str, payload: str = DEFAULT_PROBE_PAYLOAD, param: str = DEFAULT_PARAM) -> bool:
    """Retourne True seulement si le payload de test est reellement bloque.
    A appeler AVANT de router du trafic vers l'origine derriere un LB —
    un simple 'process up' ne suffit pas a prouver que le filtrage marche."""
    _, _, blocked = _probe(url, payload, param)
    return blocked


# ---------------------------------------------------------------------------
# 4. Classification de severite (grille discutee : gap x reproductibilite)
# ---------------------------------------------------------------------------

def classify_severity(gaps_ms: list, iterations: int) -> dict:
    detected = [g for g in gaps_ms if g is not None]
    if not detected:
        return {"severity": "NONE", "reason": "Aucune fenetre fail-open detectee — reload fail-closed confirme."}

    reproducibility = len(detected) / iterations
    avg_gap = sum(detected) / len(detected)
    max_gap = max(detected)

    if reproducibility >= 0.8 and max_gap > 5000:
        severity = "CRITICAL"
        reason = "Fenetre longue (>5s) et quasi systematique a chaque reload — exploitable de facon fiable."
    elif reproducibility >= 0.8:
        severity = "HIGH"
        reason = "Fenetre systematique a chaque reload — previsible si les redemarrages sont reguliers (CI/CD)."
    elif max_gap > 5000:
        severity = "HIGH"
        reason = "Fenetre longue meme si intermittente."
    elif reproducibility >= 0.3:
        severity = "MEDIUM"
        reason = "Fenetre parfois presente — a corriger, priorite selon la faille sous-jacente exposee."
    else:
        severity = "LOW"
        reason = "Fenetre rare et courte — risque residuel, a surveiller."

    return {
        "severity": severity,
        "reason": reason,
        "reproducibility_pct": round(reproducibility * 100, 1),
        "avg_gap_ms": round(avg_gap, 1),
        "max_gap_ms": round(max_gap, 1),
    }


# ---------------------------------------------------------------------------
# 5. Journalisation (payload_lab.db)
# ---------------------------------------------------------------------------

def _init_db() -> sqlite3.Connection:
    CYBERIA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(PAYLOAD_DB), timeout=10)
    con.execute("""
        CREATE TABLE IF NOT EXISTS continuity_tests (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            target_url         TEXT,
            restart_cmd        TEXT,
            payload            TEXT,
            iterations         INTEGER,
            gaps_json          TEXT,
            severity           TEXT,
            reproducibility_pct REAL,
            avg_gap_ms         REAL,
            max_gap_ms         REAL,
            tested_at          TEXT
        )
    """)
    con.commit()
    return con


def _log_cycle(target_url, restart_cmd, payload, iterations, gaps_ms, classification):
    con = _init_db()
    con.execute(
        "INSERT INTO continuity_tests "
        "(target_url, restart_cmd, payload, iterations, gaps_json, severity, "
        "reproducibility_pct, avg_gap_ms, max_gap_ms, tested_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (target_url, restart_cmd, payload, iterations, json.dumps(gaps_ms),
         classification["severity"], classification.get("reproducibility_pct"),
         classification.get("avg_gap_ms"), classification.get("max_gap_ms"), _now()),
    )
    con.commit()
    con.close()


def list_results(limit: int = 20):
    if not PAYLOAD_DB.exists():
        print("[!] Aucun resultat — lancez d'abord un cycle avec --target/--restart-cmd")
        return
    con = sqlite3.connect(str(PAYLOAD_DB), timeout=10)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT * FROM continuity_tests ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    con.close()
    if not rows:
        print("[!] Aucun resultat dans continuity_tests")
        return
    for row in rows:
        print("[{}] {} | severite={} | repro={}% | avg_gap={}ms | max_gap={}ms".format(
            row["tested_at"], row["target_url"], row["severity"],
            row["reproducibility_pct"], row["avg_gap_ms"], row["max_gap_ms"]))


# ---------------------------------------------------------------------------
# 6. Continuity Validator — orchestre N cycles et classe le resultat
# ---------------------------------------------------------------------------

def run_cycle(target_url: str, restart_cmd: str, iterations: int = 5,
              payload: str = DEFAULT_PROBE_PAYLOAD, param: str = DEFAULT_PARAM,
              cooldown_sec: float = 3.0) -> dict:
    print("[CONTINUITY] Cible : {}".format(target_url))
    print("[CONTINUITY] Commande de redemarrage : {}".format(restart_cmd))
    print("[CONTINUITY] {} iteration(s), payload={!r}".format(iterations, payload))

    gaps_ms = []
    for i in range(1, iterations + 1):
        print("\n--- Iteration {}/{} ---".format(i, iterations))
        result = measure_reload_window(target_url, restart_cmd, payload, param)
        gaps_ms.append(result["gap_duration_ms"])
        if result["gap_detected"]:
            print("  [GAP] detecte a +{}ms, duree={}ms ({} requetes non filtrees / {} envoyees)".format(
                result["gap_start_ms"], result["gap_duration_ms"],
                result["unblocked_count"], result["requests_sent"]))
        else:
            print("  [OK] Aucune fenetre detectee sur cette iteration "
                  "({} requetes envoyees)".format(result["requests_sent"]))
        if i < iterations:
            time.sleep(cooldown_sec)

    classification = classify_severity(gaps_ms, iterations)
    _log_cycle(target_url, restart_cmd, payload, iterations, gaps_ms, classification)

    print("\n=== RESULTAT CONTINUITY SHIELD ===")
    print("  Severite       : {}".format(classification["severity"]))
    print("  Justification  : {}".format(classification["reason"]))
    if classification["severity"] != "NONE":
        print("  Reproductibilite : {}%".format(classification.get("reproducibility_pct")))
        print("  Gap moyen        : {}ms".format(classification.get("avg_gap_ms")))
        print("  Gap max          : {}ms".format(classification.get("max_gap_ms")))
    print("\n  -> Journalise dans {} (table continuity_tests)".format(PAYLOAD_DB))

    return classification


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    parser = argparse.ArgumentParser(
        description="CYBERIA WAF Continuity Shield — mesure et comble la fenetre fail-open",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples:\n"
            "  python core/waf_continuity_shield.py --generate-sentinel\n"
            "  python core/waf_continuity_shield.py --target dvwa_local "
            "--restart-cmd \"sudo systemctl restart modsecurity\" --iterations 5\n"
            "  python core/waf_continuity_shield.py --url http://localhost:8080 "
            "--restart-cmd \"docker restart waf_container\"\n"
            "  python core/waf_continuity_shield.py --list-results\n"
        ),
    )
    parser.add_argument("--target", help="Nom de cible defini dans .cyberia/targets.json")
    parser.add_argument("--url", help="URL directe (alternative a --target)")
    parser.add_argument("--restart-cmd", help="Commande admin locale qui redemarre/recharge le WAF")
    parser.add_argument("--iterations", type=int, default=5, help="Nombre de cycles restart+mesure (defaut: 5)")
    parser.add_argument("--payload", default=DEFAULT_PROBE_PAYLOAD, help="Payload de test envoye en boucle")
    parser.add_argument("--param", default=DEFAULT_PARAM, help="Nom du parametre GET (defaut: q)")
    parser.add_argument("--generate-sentinel", action="store_true", help="Genere .cyberia/sentinel_gateway.conf")
    parser.add_argument("--list-results", action="store_true", help="Affiche les cycles precedents")
    args = parser.parse_args()

    if args.generate_sentinel:
        path = write_sentinel_config()
        print("[+] Sentinel Gateway genere : {}".format(path))
        print("    A inclure statiquement dans nginx (jamais recharge seul).")
        return

    if args.list_results:
        list_results()
        return

    if not args.restart_cmd:
        parser.print_help()
        print("\n[!] --restart-cmd est requis pour lancer un cycle de mesure.")
        return

    url = args.url or (get_target_url(args.target) if args.target else None)
    if not url:
        raise SystemExit("[!] Fournissez --target ou --url")

    run_cycle(url, args.restart_cmd, args.iterations, args.payload, args.param)


if __name__ == "__main__":
    _cli()
