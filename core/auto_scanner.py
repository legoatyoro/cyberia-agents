"""
core/auto_scanner.py
Scanner autonome qui combine WAF fingerprint, payload selection, analyse et rapport.

Usage:
  python core/auto_scanner.py --url http://cible.com
  python core/auto_scanner.py --url http://cible.com --output rapport.pdf
  python core/auto_scanner.py --url http://cible.com --categories xss,sqli,lfi
  python core/auto_scanner.py --url http://cible.com --no-adapt
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    import requests
except ImportError:
    print("[!] requests non installe. Lancez: pip install requests")
    raise SystemExit(1)

# ---------------------------------------------------------------------------
# Imports internes — tous avec fallback pour ne pas bloquer le demarrage
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

try:
    from core.waf_fingerprint import (
        fingerprint_waf,
        generate_bypass_prompts,
        learn_from_response,
    )
    _WAF_FP = True
except Exception as _e:
    _WAF_FP = False
    print(f"[!] waf_fingerprint non charge: {_e}")

try:
    from core.pentest_runner import (
        send_payload,
        analyze_response,
        rate_limit,
        validate_exploitation,
        save_proof,
        _print_exploit_details,
        crack_md5_hash,
    )
    _RUNNER = True
except Exception as _e:
    _RUNNER = False
    print(f"[!] pentest_runner non charge: {_e}")

if not _RUNNER:
    def validate_exploitation(category, response_body, payload):
        return {'confirmed': False, 'proof': '', 'evidence': '', 'evidence_data': []}

    def save_proof(category, payload, body, url='', status_code=0, elapsed_ms=0,
                   proof_type='', evidence_data=None):
        return ''

    def _print_exploit_details(val):
        pass

    def crack_md5_hash(hash_str):
        return {'hash': (hash_str or '').strip().lower(), 'cracked': False, 'password': None, 'level': ''}

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    _PDF = True
except ImportError:
    _PDF = False

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------

CYBERIA_DIR = ROOT / ".cyberia"
PAYLOAD_LAB_DB = CYBERIA_DIR / "payload_lab.db"
SCAN_RESULTS_DIR = CYBERIA_DIR / "scan_results"

ALL_CATEGORIES = ["xss", "sqli", "lfi", "rce", "ssti", "ssrf"]

# Mapping categorie logique -> variantes stockees dans payload_lab.db (table payloads)
CATEGORY_MAP: dict[str, list[str]] = {
    "xss":     ["xss", "xss_reflected", "xss_dom", "xss_csrf_chain", "stored_xss"],
    "sqli":    ["sqli", "sqli_blind", "sqli_auth_chain", "nosql", "nosqli"],
    "lfi":     ["lfi", "lfi_rce_chain", "path_traversal"],
    "rce":     ["rce", "cmdi", "command_injection"],
    "ssti":    ["ssti"],
    "ssrf":    ["ssrf", "ssrf_rce_chain"],
    "xxe":     ["xxe", "xxe_ssrf_chain"],
    "jwt":     ["jwt"],
    "cors":    ["cors", "csrf"],
    "graphql": ["graphql", "graphql_advanced"],
}

MAX_PAYLOADS = 20
RATE_LIMIT_SEC = 1.0
TIMEOUT = 10
ADAPT_WAIT_SEC = 30

# Cible DVWA locale : endpoints dedies par categorie (exec/, fi/) + pas de page SSTI
DVWA_LOCAL_HOSTS = ("localhost:8081", "127.0.0.1:8081")


def _is_dvwa_local(url: str) -> bool:
    return any(h in url for h in DVWA_LOCAL_HOSTS)


# Strategie de contournement affichee selon le WAF detecte (cosmetique / rapport)
# Cles alignees sur les noms retournes par core.waf_fingerprint.fingerprint_waf().
_WAF_STRATEGIES = {
    "cloudflare":  "payloads rank DIAMOND avec encodage multi-couches + fragmentation",
    "sucuri":      "encodage multi-couches + fragmentation",
    "modsecurity": "fragmentation + null bytes",
    "wordfence":   "encodage multi-couches + fragmentation",
    "imperva":     "parameter pollution + null-byte injection",
    "awswaf":      "case-mixing + commentaires SQL inline",
    "alibaba":     "encodage multi-couches + fragmentation",
    "akamai":      "normalisation unicode + chunked transfer",
    "f5bigip":     "double encodage URL + HPP",
    "fortiweb":    "encodage multi-couches + fragmentation",
    "barracuda":   "encodage multi-couches + fragmentation",
    "unknown":     "tous les payloads DIAMOND (aucun WAF detecte)",
}

# Alias entre le nom retourne par fingerprint_waf() et le token stocke dans
# imported_payloads.passed_wafs (les deux nommages divergent legerement).
_WAF_DB_ALIASES = {
    "modsecurity": "modsec",
    "awswaf": "aws_waf",
    "f5bigip": "f5_bigip",
    "fortiweb": "fortinet",
}


def _waf_db_key(waf_name: str) -> str:
    key = (waf_name or "unknown").lower()
    return _WAF_DB_ALIASES.get(key, key)


def _waf_strategy(waf_name: str) -> str:
    return _WAF_STRATEGIES.get((waf_name or "unknown").lower(), "encodage multi-couches + fragmentation")


def _waf_display_name(waf_name: str) -> str:
    if not waf_name or waf_name.lower() == "unknown":
        return "Inconnu"
    return waf_name.replace("_", " ").title()


def _count_waf_bypass_payloads(waf_name: str) -> int:
    """Compte les payloads DIAMOND/imported_payloads dont passed_wafs mentionne ce WAF."""
    if not PAYLOAD_LAB_DB.exists() or not waf_name or waf_name.lower() == "unknown":
        return 0
    try:
        con = sqlite3.connect(str(PAYLOAD_LAB_DB), timeout=5)
        count = con.execute(
            "SELECT COUNT(*) FROM imported_payloads WHERE passed_wafs LIKE ?",
            (f"%{_waf_db_key(waf_name)}%",),
        ).fetchone()[0]
        con.close()
        return count
    except Exception:
        return 0


# Verdict display
_VERDICT_ICONS = {
    "CONFIRMED":   "[CONFIRMED]",
    "LIKELY":      "[LIKELY]   ",
    "BLOCKED":     "[BLOCKED]  ",
    "INCONCLUSIVE":"[?]        ",
    "ERROR":       "[ERROR]    ",
    "NO_IMPACT":   "[-]        ",
}


# ---------------------------------------------------------------------------
# Fallback HTTP si pentest_runner absent
# ---------------------------------------------------------------------------

_last_req_time: float = 0.0


def _rate_limit() -> None:
    global _last_req_time
    elapsed = time.time() - _last_req_time
    if elapsed < RATE_LIMIT_SEC:
        time.sleep(RATE_LIMIT_SEC - elapsed)
    _last_req_time = time.time()


def _send_get(session: requests.Session, url: str, param: str, payload: str) -> tuple:
    _rate_limit()
    try:
        t0 = time.time()
        r = session.get(url, params={param: payload}, timeout=TIMEOUT, allow_redirects=False)
        elapsed = int((time.time() - t0) * 1000)
        return r.status_code, r.text, dict(r.headers), elapsed, None
    except requests.exceptions.Timeout:
        return 0, "", {}, 0, "TIMEOUT"
    except requests.exceptions.ConnectionError as exc:
        return 0, "", {}, 0, f"CONN_ERROR: {str(exc)[:60]}"
    except Exception as exc:
        return 0, "", {}, 0, f"ERROR: {str(exc)[:60]}"


def _send_post(session: requests.Session, url: str, param: str, payload: str) -> tuple:
    _rate_limit()
    try:
        t0 = time.time()
        r = session.post(url, data={param: payload, "Submit": "Submit"},
                         timeout=TIMEOUT, allow_redirects=False)
        elapsed = int((time.time() - t0) * 1000)
        return r.status_code, r.text, dict(r.headers), elapsed, None
    except requests.exceptions.Timeout:
        return 0, "", {}, 0, "TIMEOUT"
    except requests.exceptions.ConnectionError as exc:
        return 0, "", {}, 0, f"CONN_ERROR: {str(exc)[:60]}"
    except Exception as exc:
        return 0, "", {}, 0, f"ERROR: {str(exc)[:60]}"


_LFI_SIGS = [
    ("root:x:",              "etc_passwd_root"),
    ("daemon:",              "etc_passwd_daemon"),
    ("warning: include",     "php_include_error"),
    ("no such file",         "file_not_found"),
    ("failed to open stream","php_stream_error"),
    ("include",              "php_include"),
    (" fopen",               "php_fopen"),
    ("/etc/passwd",          "etc_passwd_path"),
    ("/etc/shadow",          "etc_shadow_path"),
    ("[boot loader]",        "win_boot_ini"),
    ("[extensions]",         "win_extensions"),
    ("nologin",              "nologin_shell"),
    ("/bin/bash",            "bin_bash"),
    ("/bin/sh",              "bin_sh"),
]

_RCE_SIGS = [
    ("bytes from",  "ping_executed"),
    ("ping",        "ping_output"),
    ("64 bytes",    "ping_64bytes"),
    ("time=",       "ping_time"),
    ("ttl=",        "ping_ttl"),
    ("www-data",    "www_data_user"),
    ("uid=",        "id_executed"),
    ("hello world", "rce_hello_world"),
    ("root:",       "root_user"),
    ("inet ",       "ifconfig_inet"),
    ("windows",     "windows_output"),
]


def _simple_analyze(status: int, body: str, payload: str, category: str) -> dict:
    """Analyse heuristique minimale si analyze_response n'est pas dispo."""
    body_lower = body.lower() if body else ""
    if status in (403, 406, 429):
        return {"verdict": "BLOCKED", "evidence": f"HTTP {status}", "score": 0}
    if status == 0:
        return {"verdict": "ERROR", "evidence": "no response", "score": 0}

    if category == "lfi":
        for sig, name in _LFI_SIGS:
            if sig in body_lower:
                return {"verdict": "CONFIRMED", "evidence": name, "score": 80}
        # Heuristique: body long avec separateurs de fichiers
        if status == 200 and len(body) > 5000 and '/' in body:
            colon_count = body.count(':')
            if colon_count >= 3:
                return {"verdict": "LIKELY", "evidence": f"lfi_heuristic_{colon_count}colons", "score": 50}

    if category == "rce":
        for sig, name in _RCE_SIGS:
            if sig.lower() in body_lower:
                return {"verdict": "CONFIRMED", "evidence": name, "score": 80}

    if payload.lower() in body_lower:
        return {"verdict": "CONFIRMED", "evidence": "payload_reflected", "score": 80}

    # Signatures generiques multi-categories
    generic_sigs = ["first name", "surname", "gordon", "pablo", "smithy", "bob",
                    "root:x:", "uid=0", "etc/passwd"]
    for sig in generic_sigs:
        if sig in body_lower:
            return {"verdict": "CONFIRMED", "evidence": f"leak_sig:{sig}", "score": 75}

    if status == 200:
        return {"verdict": "INCONCLUSIVE", "evidence": "none", "score": 20}
    return {"verdict": "NO_IMPACT", "evidence": f"HTTP {status}", "score": 5}


_PAYLOAD_FILTERS: dict[str, list[str]] = {
    "xss":  ["<", ">", "script", "alert", "onerror", "onload", "javascript", "vbscript", "svg", "img"],
    "sqli": ["'", '"', "union", "select", "or", "and", "insert", "drop"],
    "lfi":  ["../", "..\\", "%2e", "%c0", "%5c", "%252e", "passwd", "etc", "....", "..%", "%2f%2e", "file://"],
    "rce":  [";", "|", "&", "`", "$", "(", ")", "cmd", "bash", "sh"],
    "ssti": ["{{", "}}", "{%", "%}", "${", "<%", "%>", "#{"],
    "ssrf": ["http://", "https://", "file://", "gopher://", "dict://", "0x", "169.254"],
}


def filter_valid_payloads(payloads: list[str], category: str) -> list[str]:
    """Garde uniquement les payloads dont le contenu correspond a la categorie."""
    tokens = _PAYLOAD_FILTERS.get(category, [])
    if not tokens:
        return payloads
    result = []
    for p in payloads:
        p_lower = p.lower()
        if any(t.lower() in p_lower for t in tokens):
            result.append(p)
    return result


def dvwa_login(base_url: str) -> requests.Session:
    """Login DVWA, retourne une Session avec cookies admin valides."""
    s = requests.Session()
    s.headers.update({"User-Agent": "CYBERIA-AutoScanner/1.0"})
    try:
        page = s.get(base_url + "/login.php", timeout=TIMEOUT)
        token = re.search(r"user_token.*?value=['\"]([^'\"]+)['\"]", page.text)
        user_token = token.group(1) if token else ""
        s.post(base_url + "/login.php", data={
            "username": "admin",
            "password": "password",
            "Login": "Login",
            "user_token": user_token,
        }, timeout=TIMEOUT)
        s.get(base_url + "/security.php?security=low", timeout=TIMEOUT)
        print("  [DVWA] Login OK — session admin active")
    except Exception as exc:
        print(f"  [DVWA] Login echoue: {exc}")
    return s


# ---------------------------------------------------------------------------
# AutoScanner
# ---------------------------------------------------------------------------

class AutoScanner:
    def __init__(self, url: str, target_name: str = ""):
        self.url = url.rstrip("/")
        parsed = urlparse(url)
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.path = parsed.path or "/"
        qs = parse_qs(parsed.query, keep_blank_values=True)
        self.param_name = list(qs.keys())[0] if qs else "q"
        self.target_name = target_name or parsed.netloc.replace(":", "_")

        self.target = {
            "base_url": self.base_url,
            "type": "custom",
            "headers": {"User-Agent": "CYBERIA-AutoScanner/1.0"},
            "auth": {},
            "timeout": TIMEOUT,
        }
        self.endpoint_base = {
            "path": self.path,
            "method": "GET",
            "param": self.param_name,
        }

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "CYBERIA-AutoScanner/1.0"})

        self.waf_result: dict = {"waf": "unknown", "confidence": 0, "signatures": [], "headers": {}}
        self.results: dict = {}
        self.scan_start: str = ""

    # ------------------------------------------------------------------
    # Entrypoint principal
    # ------------------------------------------------------------------

    def run(self, categories: list[str] | None = None, adapt: bool = True) -> dict:
        self.scan_start = datetime.now(timezone.utc).isoformat()
        cats = categories or ALL_CATEGORIES

        # ETAPE 1 — WAF fingerprint
        _header("ETAPE 1/4 — WAF FINGERPRINT")
        if _WAF_FP:
            self.waf_result = fingerprint_waf(self.url)
        else:
            self.waf_result = {"waf": "unknown", "confidence": 0, "signatures": [], "headers": {}}
        waf = self.waf_result["waf"]
        conf = self.waf_result["confidence"]
        sigs = self.waf_result.get("signatures", [])
        bypass_count = _count_waf_bypass_payloads(waf)
        print(f"  WAF détecté : {_waf_display_name(waf)} ({conf}%)")
        print(f"  Payloads WAF bypass disponibles : {bypass_count}")
        print(f"  Stratégie : {_waf_strategy(waf)}")
        if sigs:
            print(f"  Signatures   : {', '.join(sigs[:4])}")
        print()

        # Login DVWA si cible locale
        if "localhost" in self.url or "127.0.0.1" in self.url:
            print("  [DVWA] Cible locale detectee — login admin...")
            self.session = dvwa_login(self.base_url)

        # ETAPE 2 — Scan par categorie
        _header(f"ETAPE 2/4 — SCAN ({', '.join(c.upper() for c in cats)})")
        for cat in cats:
            print(f"\n  --- {cat.upper()} ---")
            stats = self.scan_category(cat)
            self.results[cat] = stats

            if stats.get("skipped"):
                continue

            bypass = stats["bypass_rate"]
            _bar = "#" * int(bypass / 5) + "." * (20 - int(bypass / 5))
            print(f"  Bypass rate  : {bypass:.1f}% [{_bar}]")
            print(f"  CONFIRMED={stats['confirmed']} BLOCKED={stats['blocked']} "
                  f"INCONCLUSIVE={stats['inconclusive']} ERRORS={stats['errors']}")

            if adapt and bypass < 30.0:
                print(f"  [!] Bypass < 30% — adaptation WAF [{waf}]...")
                self.adapt_payloads(cat, waf)

        # ETAPE 3 — Rapport
        _header("ETAPE 3/4 — RAPPORT JSON")
        report_path = self.generate_report()
        print(f"  Sauvegarde   : {report_path}")

        # ETAPE 4 — Resume
        _header("ETAPE 4/4 — RESUME FINAL")
        self._print_summary()
        self._print_data_summary()
        self._print_cracked_hashes()

        # Lister les preuves HTML generees pendant ce scan
        proofs_dir = CYBERIA_DIR / "proofs"
        if proofs_dir.exists():
            html_proofs = sorted(proofs_dir.glob("*_proof.html"))
            if html_proofs:
                _GREEN = '\033[92m'
                _RESET = '\033[0m'
                print(f"{_GREEN}  Preuves HTML generees : {proofs_dir}{_RESET}")
                for p in html_proofs:
                    size_kb = p.stat().st_size / 1024
                    print(f"{_GREEN}    {p.name}  ({size_kb:.1f} KB){_RESET}")

        return self.results

    # ------------------------------------------------------------------
    # Scan d'une categorie
    # ------------------------------------------------------------------

    def scan_category(self, category: str, payloads: list[str] | None = None) -> dict:
        is_dvwa = _is_dvwa_local(self.url)

        # DVWA n'a pas de page SSTI dediee — inutile de scanner
        if category == "ssti" and is_dvwa:
            print(f"  [SKIPPED] DVWA ne propose pas de page SSTI — categorie ignoree")
            stats = _empty_stats(category)
            stats["skipped"] = True
            return stats

        if payloads is None:
            payloads = self._load_payloads(category)

        if not payloads:
            print(f"  [!] Aucun payload {category.upper()} dans payload_lab.db")
            return _empty_stats(category)

        print(f"  {len(payloads)} payloads charges")

        endpoint = {**self.endpoint_base, "vuln_type": category}
        target_url = self.base_url + self.path
        param = self.param_name

        # RCE DVWA : POST /vulnerabilities/exec/ avec ip=PAYLOAD&Submit=Submit
        use_post = category == "rce" and "exec" in self.path
        if category == "rce" and is_dvwa:
            endpoint["path"] = "/vulnerabilities/exec/"
            endpoint["param"] = "ip"
            param = "ip"
            target_url = self.base_url + "/vulnerabilities/exec/"
            use_post = True
        if use_post:
            endpoint["method"] = "POST"

        # LFI DVWA : GET /vulnerabilities/fi/?page=PAYLOAD
        if category == "lfi" and is_dvwa:
            endpoint["path"] = "/vulnerabilities/fi/"
            endpoint["param"] = "page"
            param = "page"
            target_url = self.base_url + "/vulnerabilities/fi/"

        stats = _empty_stats(category)

        for payload in payloads:
            if _RUNNER:
                try:
                    status, body, headers, elapsed_ms, error = send_payload(
                        self.target, endpoint, payload, self.session
                    )
                except Exception as exc:
                    status, body, headers, elapsed_ms, error = 0, "", {}, 0, str(exc)
            else:
                if use_post:
                    status, body, headers, elapsed_ms, error = _send_post(
                        self.session, target_url, param, payload
                    )
                else:
                    status, body, headers, elapsed_ms, error = _send_get(
                        self.session, target_url, param, payload
                    )

            if error and status == 0:
                stats["errors"] += 1
                print(f"    {'ERROR':12s} {payload[:45]} [{error[:30]}]")
                continue

            if _RUNNER:
                try:
                    result = analyze_response(status, body, headers, elapsed_ms, category, payload)
                except Exception:
                    result = _simple_analyze(status, body, payload, category)
            else:
                result = _simple_analyze(status, body, payload, category)

            verdict = result["verdict"]
            evidence = result["evidence"]
            stats["total"] += 1

            val = validate_exploitation(category, body, payload)
            if val["confirmed"]:
                _GREEN = '\033[92m'
                _RESET = '\033[0m'
                print(f"{_GREEN}  ★ PREUVE : {val['proof']} [{category.upper()}]{_RESET}")
                _print_exploit_details(val)
                proof_path = save_proof(
                    category, payload, body,
                    url=target_url,
                    status_code=status,
                    elapsed_ms=elapsed_ms,
                    proof_type=val["proof"],
                    evidence_data=val.get("evidence_data", []),
                )
                if proof_path:
                    print(f"{_GREEN}  [PROOF SAVED] {proof_path}{_RESET}")

            if verdict == "CONFIRMED":
                stats["confirmed"] += 1
                stats["hits"].append({
                    "payload": payload,
                    "evidence": evidence,
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                    "proof": val["proof"],
                    "exploit_evidence": val["evidence"],
                    "evidence_data": val.get("evidence_data", []),
                })
            elif verdict in ("BLOCKED",):
                stats["blocked"] += 1
            elif verdict == "LIKELY":
                stats["confirmed"] += 1  # compter LIKELY comme bypass
                stats["hits"].append({
                    "payload": payload,
                    "evidence": f"LIKELY: {evidence}",
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                    "proof": val["proof"],
                    "exploit_evidence": val["evidence"],
                    "evidence_data": val.get("evidence_data", []),
                })
            else:
                stats["inconclusive"] += 1

            icon = _VERDICT_ICONS.get(verdict, "[?]")
            print(f"    {icon} {payload[:45]:<45} [{status}] {elapsed_ms}ms")

            if _WAF_FP:
                try:
                    learn_from_response(
                        url=self.base_url + self.path,
                        payload=payload,
                        status_code=status,
                        response_headers=headers,
                        waf_name=self.waf_result.get("waf", "unknown"),
                        payload_type=category,
                        verdict=verdict,
                    )
                except Exception:
                    pass

        total = stats["total"]
        not_blocked = stats["confirmed"] + stats["inconclusive"]
        stats["bypass_rate"] = round(not_blocked / total * 100, 1) if total > 0 else 0.0
        return stats

    # ------------------------------------------------------------------
    # Adaptation WAF-specifique
    # ------------------------------------------------------------------

    def adapt_payloads(self, category: str, waf_name: str) -> dict:
        if not _WAF_FP:
            print("  [!] waf_fingerprint indisponible — adaptation ignoree")
            return {"new_payloads": 0}

        entry = generate_bypass_prompts(waf_name, category)
        print(f"  Prompt injecte dans supervisor_prompts.json "
              f"(priorite={entry['priority']}, ttl={entry['ttl']})")
        print(f"  Attente {ADAPT_WAIT_SEC}s pour evolve_live_v2...")

        timestamp_before = datetime.now(timezone.utc).isoformat()
        for remaining in range(ADAPT_WAIT_SEC, 0, -10):
            print(f"    ... {remaining}s restantes", end="\r", flush=True)
            time.sleep(min(10, remaining))
        print(" " * 40, end="\r")

        new_payloads = self._load_recent_payloads(category, since=timestamp_before)
        if not new_payloads:
            print(f"  [!] Aucun nouveau payload genere (evolve_live_v2 actif ?)")
            return {"new_payloads": 0}

        print(f"  {len(new_payloads)} nouveaux payloads detectes — re-test...")
        retry_stats = self.scan_category(category, payloads=new_payloads)

        # Fusionner dans les resultats principaux
        if category in self.results:
            self.results[category]["retry"] = retry_stats
            # Si le retry ameliore le bypass, mettre a jour les hits
            if retry_stats["bypass_rate"] > self.results[category]["bypass_rate"]:
                self.results[category]["hits"].extend(retry_stats["hits"])

        return {"new_payloads": len(new_payloads), "retry_stats": retry_stats}

    # ------------------------------------------------------------------
    # Rapport
    # ------------------------------------------------------------------

    def generate_report(self, output_path: str = "") -> str:
        SCAN_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        ts = now.strftime("%Y-%m-%d_%H-%M")
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", self.target_name)[:40]
        base_name = f"{ts}_{safe_name}"

        report = {
            "scan_id": base_name,
            "url": self.url,
            "target_name": self.target_name,
            "scanned_at": self.scan_start,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "waf": self.waf_result,
            "results": self.results,
            "summary": self._build_summary(),
        }

        # Toujours sauvegarder en JSON
        json_path = SCAN_RESULTS_DIR / f"{base_name}.json"
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Rapport additionnel si --output specifie
        if output_path:
            if output_path.lower().endswith(".pdf") and _PDF:
                self._write_pdf(report, output_path)
                print(f"  PDF          : {output_path}")
            elif output_path.lower().endswith(".pdf") and not _PDF:
                txt_path = output_path.replace(".pdf", ".txt")
                self._write_txt(report, txt_path)
                print(f"  [!] reportlab absent — rapport texte : {txt_path}")
            elif output_path.lower().endswith(".json"):
                import shutil
                shutil.copy(str(json_path), output_path)
                print(f"  JSON copie   : {output_path}")
            else:
                self._write_txt(report, output_path)
                print(f"  Texte        : {output_path}")

        return str(json_path)

    # ------------------------------------------------------------------
    # Helpers internes
    # ------------------------------------------------------------------

    def _load_payloads(self, category: str) -> list[str]:
        if not PAYLOAD_LAB_DB.exists():
            return []
        variants = CATEGORY_MAP.get(category, [category])
        waf_name = self.waf_result.get("waf", "unknown")
        try:
            con = sqlite3.connect(str(PAYLOAD_LAB_DB), timeout=5)
            placeholders = ",".join("?" * len(variants))

            # Priorite 1 : payloads DIAMOND ayant deja bypass ce WAF specifique
            diamond_rows = []
            if waf_name and waf_name.lower() != "unknown":
                diamond_rows = con.execute(
                    f"SELECT payload FROM imported_payloads "
                    f"WHERE payload_type IN ({placeholders}) AND rank='DIAMOND' "
                    f"AND passed_wafs LIKE ? ORDER BY waf_score DESC",
                    (*variants, f"%{_waf_db_key(waf_name)}%"),
                ).fetchall()

            # Priorite 2 : tous les payloads DIAMOND de la categorie
            diamond_all_rows = con.execute(
                f"SELECT payload FROM imported_payloads "
                f"WHERE payload_type IN ({placeholders}) AND rank='DIAMOND' "
                f"ORDER BY waf_score DESC",
                variants,
            ).fetchall()

            # Reste : payloads generiques de la table payloads
            rows = con.execute(
                f"SELECT payload FROM payloads WHERE category IN ({placeholders})",
                variants,
            ).fetchall()
            con.close()

            diamond_priority = [r[0] for r in diamond_rows]
            diamond_rest = [r[0] for r in diamond_all_rows]
            generic = [r[0] for r in rows]

            seen = set()
            ordered = []
            diamond_count = 0
            for p in diamond_priority + diamond_rest:
                if p not in seen:
                    seen.add(p)
                    ordered.append(p)
                    diamond_count += 1
            for p in generic:
                if p not in seen:
                    seen.add(p)
                    ordered.append(p)

            print(f"  {len(ordered)} payloads charges pour categorie {category}")
            if diamond_count:
                print(f"  -> {diamond_count} payloads DIAMOND priorises")
            return ordered
        except Exception:
            return []

    def _load_recent_payloads(self, category: str, since: str) -> list[str]:
        if not PAYLOAD_LAB_DB.exists():
            return []
        try:
            con = sqlite3.connect(str(PAYLOAD_LAB_DB), timeout=5)
            rows = con.execute(
                "SELECT payload FROM imported_payloads "
                "WHERE payload_type LIKE ? AND imported_at > ? "
                "ORDER BY imported_at DESC LIMIT 10",
                (f"%{category}%", since),
            ).fetchall()
            con.close()
            return [r[0] for r in rows]
        except Exception:
            return []

    def _build_summary(self) -> dict:
        total_confirmed = sum(r.get("confirmed", 0) for r in self.results.values())
        total_blocked = sum(r.get("blocked", 0) for r in self.results.values())
        total_payloads = sum(r.get("total", 0) for r in self.results.values())
        overall_bypass = round(
            (total_payloads - total_blocked) / total_payloads * 100, 1
        ) if total_payloads > 0 else 0.0

        vulnerable_cats = [
            cat for cat, r in self.results.items() if r.get("confirmed", 0) > 0
        ]
        return {
            "total_payloads_tested": total_payloads,
            "total_confirmed": total_confirmed,
            "total_blocked": total_blocked,
            "overall_bypass_rate": overall_bypass,
            "vulnerable_categories": vulnerable_cats,
            "waf": self.waf_result.get("waf", "unknown"),
            "waf_confidence": self.waf_result.get("confidence", 0),
        }

    def _print_summary(self) -> None:
        s = self._build_summary()
        print(f"  Cible        : {self.url}")
        print(f"  WAF          : {s['waf'].upper()} ({s['waf_confidence']}%)")
        print(f"  Payloads     : {s['total_payloads_tested']} testes")
        print(f"  Bypass rate  : {s['overall_bypass_rate']}%")
        print(f"  CONFIRMED    : {s['total_confirmed']}")
        print(f"  BLOCKED      : {s['total_blocked']}")
        if s["vulnerable_categories"]:
            print(f"\n  VULNERABILITES CONFIRMEES :")
            for cat in s["vulnerable_categories"]:
                hits = self.results[cat].get("hits", [])
                print(f"    [{cat.upper():6s}] {len(hits)} hit(s)")
                for h in hits[:3]:
                    print(f"           {h['payload'][:60]}")
                    print(f"           evidence: {h['evidence'][:80]}")
        else:
            print(f"\n  Aucune vulnerabilite confirmee.")
        print()

    def _print_data_summary(self) -> None:
        """Tableau recapitulatif des donnees sensibles extraites (toutes categories)."""
        seen = set()
        items = []
        for stats in self.results.values():
            for hit in stats.get("hits", []):
                for item in hit.get("evidence_data", []):
                    key = (str(item.get("type", "")), str(item.get("value", "")).lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(item)

        if not items:
            return

        crit_display = {
            "CRITIQUE": "\U0001F534 CRITIQUE",
            "ELEVE": "\U0001F7E0 ELEVE",
            "ÉLEVÉ": "\U0001F7E0 ELEVE",
            "MOYEN": "\U0001F7E1 MOYEN",
        }
        rows = [
            (
                str(item.get("value", ""))[:28],
                str(item.get("type", ""))[:20],
                crit_display.get(item.get("criticality", "MOYEN"), "\U0001F7E1 MOYEN"),
            )
            for item in items[:30]
        ]

        w1 = max(len("Donnee"), max(len(r[0]) for r in rows))
        w2 = max(len("Type"), max(len(r[1]) for r in rows))
        w3 = max(len("Criticite"), max(len(r[2]) for r in rows))

        def _sep(left, mid, right):
            return "  " + left + "─" * (w1 + 2) + mid + "─" * (w2 + 2) + mid + "─" * (w3 + 2) + right

        print("  DONNEES SENSIBLES EXTRAITES\n")
        _safe_print(_sep("┌", "┬", "┐"))
        _safe_print("  │ {:<{w1}} │ {:<{w2}} │ {:<{w3}} │".format("Donnee", "Type", "Criticite", w1=w1, w2=w2, w3=w3))
        _safe_print(_sep("├", "┼", "┤"))
        for value, dtype, crit in rows:
            _safe_print("  │ {:<{w1}} │ {:<{w2}} │ {:<{w3}} │".format(value, dtype, crit, w1=w1, w2=w2, w3=w3))
        _safe_print(_sep("└", "┴", "┘"))
        if len(items) > len(rows):
            print(f"  (+{len(items) - len(rows)} donnee(s) supplementaire(s), voir le rapport JSON)")
        print()

    def _print_cracked_hashes(self) -> None:
        """Tentative de crack (dictionnaire local uniquement) pour chaque hash MD5 extrait."""
        seen = set()
        hashes = []
        for stats in self.results.values():
            for hit in stats.get("hits", []):
                for item in hit.get("evidence_data", []):
                    if item.get("type") == "Hash MD5":
                        h = str(item.get("value", "")).lower()
                        if h and h not in seen:
                            seen.add(h)
                            hashes.append(h)

        if not hashes:
            return

        print("  HASHES MD5 — TENTATIVE DE CRACK (dictionnaire local)\n")
        for h in hashes:
            result = crack_md5_hash(h)
            _safe_print(f"  Hash    : {result['hash']}")
            if result["cracked"]:
                _safe_print(f"  Cracké  : ✅ OUI")
                _safe_print(f'  Mot de passe réel : "{result["password"]}"')
                _safe_print(f"  Niveau  : {result['level']}")
            else:
                _safe_print(f"  Cracké  : ❌ NON (absent du dictionnaire local)")
            print()

    # ------------------------------------------------------------------
    # Ecriture PDF et TXT
    # ------------------------------------------------------------------

    def _write_pdf(self, report: dict, path: str) -> None:
        doc = SimpleDocTemplate(path, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        title_style = ParagraphStyle("Title", parent=styles["Title"],
                                     textColor=colors.HexColor("#003300"))
        h2 = ParagraphStyle("H2", parent=styles["Heading2"],
                             textColor=colors.HexColor("#006600"))
        mono = ParagraphStyle("Mono", parent=styles["Code"], fontSize=7)

        story.append(Paragraph("CYBERIA AUTO-SCAN REPORT", title_style))
        story.append(Spacer(1, 12))
        story.append(Paragraph(f"URL     : {report['url']}", styles["Normal"]))
        story.append(Paragraph(f"Date    : {report['scanned_at'][:19]}", styles["Normal"]))
        s = report["summary"]
        story.append(Paragraph(f"WAF     : {s['waf'].upper()} ({s['waf_confidence']}%)", styles["Normal"]))
        story.append(Paragraph(f"Bypass  : {s['overall_bypass_rate']}%", styles["Normal"]))
        story.append(Spacer(1, 16))

        for cat, stats in report["results"].items():
            story.append(Paragraph(cat.upper(), h2))
            data = [["Payload", "Evidence", "Status", "ms"]]
            for h in stats.get("hits", []):
                data.append([
                    h["payload"][:50],
                    h["evidence"][:40],
                    str(h.get("status", "")),
                    str(h.get("elapsed_ms", "")),
                ])
            if len(data) > 1:
                tbl = Table(data, colWidths=[200, 160, 50, 40])
                tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#003300")),
                    ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE",   (0, 0), (-1, -1), 7),
                    ("GRID",       (0, 0), (-1, -1), 0.5, colors.grey),
                ]))
                story.append(tbl)
            else:
                story.append(Paragraph("Aucun hit confirme.", styles["Normal"]))
            story.append(Spacer(1, 10))

        doc.build(story)

    def _write_txt(self, report: dict, path: str) -> None:
        lines = [
            "=" * 60,
            "  CYBERIA AUTO-SCAN REPORT",
            "=" * 60,
            f"URL     : {report['url']}",
            f"Date    : {report['scanned_at'][:19]}",
            f"WAF     : {report['summary']['waf'].upper()} "
            f"({report['summary']['waf_confidence']}%)",
            f"Bypass  : {report['summary']['overall_bypass_rate']}%",
            "",
        ]
        for cat, stats in report["results"].items():
            lines.append(f"[{cat.upper()}]")
            lines.append(f"  Total={stats.get('total',0)} "
                         f"CONFIRMED={stats.get('confirmed',0)} "
                         f"BLOCKED={stats.get('blocked',0)} "
                         f"bypass={stats.get('bypass_rate',0)}%")
            for h in stats.get("hits", []):
                lines.append(f"  HIT: {h['payload'][:70]}")
                lines.append(f"       {h['evidence'][:80]}")
            lines.append("")

        Path(path).write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_stats(category: str) -> dict:
    return {
        "category": category,
        "total": 0,
        "confirmed": 0,
        "blocked": 0,
        "inconclusive": 0,
        "errors": 0,
        "bypass_rate": 0.0,
        "hits": [],
    }


def _header(title: str) -> None:
    w = 60
    print("\n" + "=" * w)
    print(f"  {title}")
    print("=" * w)


def _safe_print(text: str) -> None:
    """Print resistant aux consoles non-UTF8 (box-drawing / emoji sur Windows cp1252)."""
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="CYBERIA AutoScanner — scanner autonome complet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples:\n"
            "  python core/auto_scanner.py --url http://cible.com\n"
            "  python core/auto_scanner.py --url http://cible.com --output rapport.pdf\n"
            "  python core/auto_scanner.py --url http://cible.com --categories xss,sqli\n"
            "  python core/auto_scanner.py --url http://cible.com --no-adapt\n"
        ),
    )
    parser.add_argument("--url", required=True, help="URL cible (ex: http://cible.com/page?param=)")
    parser.add_argument("--output", default="", help="Chemin rapport de sortie (.pdf, .json, .txt)")
    parser.add_argument("--categories", default="",
                        help="Categories a tester, separees par virgule (defaut: toutes)")
    parser.add_argument("--no-adapt", action="store_true",
                        help="Desactive l'adaptation WAF (skip generate_bypass_prompts + attente 30s)")
    parser.add_argument("--name", default="",
                        help="Nom de la cible pour le rapport (defaut: hostname)")
    args = parser.parse_args()

    cats = [c.strip() for c in args.categories.split(",") if c.strip()] if args.categories else None
    if cats:
        unknown = [c for c in cats if c not in ALL_CATEGORIES]
        if unknown:
            print(f"[!] Categories inconnues: {', '.join(unknown)}")
            print(f"    Valides: {', '.join(ALL_CATEGORIES)}")
            raise SystemExit(1)

    scanner = AutoScanner(url=args.url, target_name=args.name)
    scanner.run(categories=cats, adapt=not args.no_adapt)

    if args.output:
        scanner.generate_report(output_path=args.output)


if __name__ == "__main__":
    _cli()
