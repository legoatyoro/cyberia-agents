"""CYBERIA Payload Lab Dashboard â€” advanced Textual UI for payload testing and analysis."""

import os
import threading
import time
import sqlite3
import webbrowser
import requests
import re
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button, Select, Static, RichLog,
    ListView, ListItem, Label, Input,
)
from textual.screen import ModalScreen

DB_PATH = Path(".cyberia/payload_lab.db")
DVWA_BASE = "http://localhost:8081"
DVWA_LOGIN_URL = f"{DVWA_BASE}/login.php"

ENDPOINTS = {
    "xss":   {"url": f"{DVWA_BASE}/vulnerabilities/xss_r/", "param": "name", "method": "GET"},
    "sqli":  {"url": f"{DVWA_BASE}/vulnerabilities/sqli/",  "param": "id",   "method": "GET"},
    "lfi":   {"url": f"{DVWA_BASE}/vulnerabilities/fi/",    "param": "page", "method": "GET"},
    "rce":   {"url": f"{DVWA_BASE}/vulnerabilities/exec/",  "param": "ip",   "method": "POST"},
    "ssti":  {"url": f"{DVWA_BASE}/vulnerabilities/xss_r/", "param": "name", "method": "GET"},
    "ssrf":  {"url": f"{DVWA_BASE}/vulnerabilities/xss_r/", "param": "name", "method": "GET"},
    "mixed": {"url": f"{DVWA_BASE}/vulnerabilities/sqli/",  "param": "id",   "method": "GET"},
}

RANK_COLORS = {
    "DIAMOND": "#00ffff",
    "ELITE":   "#ff00ff",
    "VETERAN": "#ffaa00",
    "ALL":     "#00ff41",
}

IMPACT_DESCRIPTIONS = {
    'xss': 'Ce payload injecte du JavaScript dans la page.\nImpact : vol de cookies, redirection, keylogger, defacement.',
    'sqli': 'Ce payload extrait les donnees de la base de donnees.\nImpact : lecture/modification/suppression de donnees, contournement auth.',
    'lfi': 'Ce payload lit des fichiers systeme sur le serveur.\nImpact : lecture /etc/passwd, fichiers de config, code source.',
    'rce': 'Ce payload execute des commandes systeme sur le serveur.\nImpact : controle total du serveur, reverse shell, exfiltration.',
    'ssti': 'Ce payload injecte du code dans un template serveur.\nImpact : execution de code, lecture de fichiers, controle serveur.',
    'ssrf': 'Ce payload force le serveur a faire des requetes internes.\nImpact : acces aux metadata cloud, services internes, scan reseau.',
    'xxe': 'Ce payload injecte du XML avec des entites externes.\nImpact : lecture de fichiers, SSRF, deni de service.',
    'mixed': 'Ce payload combine plusieurs techniques.\nImpact : depend des vecteurs utilises.',
}

CSS = """
Screen {
    background: #0a0a0a;
    layout: horizontal;
}

#panel-left {
    width: 28;
    background: #0d0d0d;
    border: solid #00ff41;
    padding: 1;
    height: 100%;
}

#panel-center {
    background: #0d0d0d;
    border: solid #00ff41;
    padding: 1;
}

#panel-right {
    width: 38;
    background: #0d0d0d;
    border: solid #00ff41;
    padding: 1;
}

Static {
    background: #0d0d0d;
    color: #00ff41;
}

Select {
    border: solid #00ff41;
    color: #00ff41;
    margin-bottom: 1;
}

Button {
    background: #0d0d0d;
    border: solid #00ff41;
    color: #00ff41;
    margin-bottom: 1;
    width: 100%;
}

Button:hover {
    background: #003300;
}

Button.-error {
    border: solid #ff0000;
    color: #ff0000;
}

RichLog {
    background: #0d0d0d;
    color: #00ff41;
    height: 1fr;
}

ListView {
    background: #0d0d0d;
    border: solid #004400;
    height: 1fr;
    margin-bottom: 1;
}

ListItem {
    color: #00ff41;
    background: #0d0d0d;
    padding: 0 1;
}

ListItem:hover {
    background: #002200;
}

ListItem.--highlight {
    background: #003300;
}

#lbl-title {
    text-align: center;
    color: #00ff41;
    text-style: bold;
    margin-bottom: 1;
}

#lbl-count {
    color: #00cc33;
    height: auto;
    margin-bottom: 1;
}

#lbl-payload-detail {
    color: #00ff41;
    height: auto;
    margin-bottom: 1;
}

#custom-url {
    background: #0d0d0d;
    border: solid #00ff41;
    color: #ffff00;
    margin-bottom: 1;
}

#btn-copy {
    background: #0d0d0d;
    border: solid #00ccff;
    color: #00ccff;
    margin-bottom: 1;
    width: 100%;
}

#btn-test-url {
    background: #0d0d0d;
    border: solid #ffaa00;
    color: #ffaa00;
    margin-bottom: 1;
    width: 100%;
}

#btn-browser {
    background: #0d0d0d;
    border: solid #ff00ff;
    color: #ff00ff;
    margin-bottom: 1;
    width: 100%;
}

#dialog-box {
    width: 52;
    height: 12;
    background: #0d0d0d;
    border: solid #00ff41;
    padding: 2;
    align: center middle;
    margin: 1 2;
}

#dlg-msg {
    text-align: center;
    margin-bottom: 2;
    color: #ffff00;
    height: auto;
}

#dlg-buttons {
    align: center middle;
    height: auto;
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dvwa_login(session: requests.Session) -> bool:
    try:
        r = session.get(DVWA_LOGIN_URL, timeout=5)
        token_m = re.search(r"user_token.*?value=['\"]([^'\"]+)['\"]", r.text)
        csrf = token_m.group(1) if token_m else ""
        r2 = session.post(DVWA_LOGIN_URL, data={
            "username": "admin", "password": "password",
            "Login": "Login", "user_token": csrf,
        }, timeout=5)
        session.get(f"{DVWA_BASE}/security.php", timeout=5)
        session.post(f"{DVWA_BASE}/security.php", data={
            "security": "low", "seclev_submit": "Submit", "user_token": csrf,
        }, timeout=5)
        return r2.status_code == 200
    except Exception:
        return False


def _load_from_db(category: str, rank: str) -> list[dict]:
    if not DB_PATH.exists():
        return []
    try:
        con = sqlite3.connect(str(DB_PATH), timeout=5)
        if rank == "ALL":
            rows = con.execute(
                "SELECT payload, waf_score, rank, payload_type FROM imported_payloads "
                "WHERE payload_type LIKE ? ORDER BY waf_score DESC LIMIT 100",
                (f"%{category}%",),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT payload, waf_score, rank, payload_type FROM imported_payloads "
                "WHERE payload_type LIKE ? AND rank=? ORDER BY waf_score DESC LIMIT 100",
                (f"%{category}%", rank),
            ).fetchall()
        con.close()
        return [
            {"payload": r[0], "waf_score": r[1] or 0, "rank": r[2] or "?", "payload_type": r[3] or category}
            for r in rows
        ]
    except Exception:
        return []


def _call_mimo(payload: str) -> str:
    try:
        from openai import OpenAI
        api_key = os.getenv("MIMO_API_KEY", "")
        if not api_key:
            return "(MIMO_API_KEY non definie â€” explication indisponible)"
        client = OpenAI(api_key=api_key, base_url="https://api.xiaomimimo.com/v1")
        resp = client.chat.completions.create(
            model="mimo-v2.5-pro",
            messages=[{"role": "user", "content": (
                f"Explique en 3 lignes ce que fait ce payload de securite : {payload}. "
                "Quel est son impact ? Quelle vulnerabilite exploite-t-il ?"
            )}],
            max_tokens=150,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        return f"(Erreur MiMo: {exc})"


def _verdict(status: int, body: str, payload: str) -> tuple[str, str]:
    body_lower = body.lower() if body else ""
    if status == 403:
        return "BLOCKED", "bold red"
    if status == 200 and payload.lower() in body_lower:
        return "CONFIRMED", "bold green"
    leak_sigs = ["first name", "surname", "gordon", "pablo", "smithy", "bob"]
    if any(s in body_lower for s in leak_sigs):
        return "CONFIRMED", "bold green"
    if status == 200:
        return "INCONCLUSIVE", "yellow"
    return "ERROR", "red"


# ---------------------------------------------------------------------------
# Confirm dialog
# ---------------------------------------------------------------------------

class ConfirmDialog(ModalScreen):
    def __init__(self, message: str):
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-box"):
            yield Static(self._message, id="dlg-msg")
            with Horizontal(id="dlg-buttons"):
                yield Button("OUI â€” SUPPRIMER", id="dlg-yes", variant="error")
                yield Button("ANNULER", id="dlg-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "dlg-yes")


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

class PayloadLabDashboard(App):
    CSS = CSS
    TITLE = "CYBERIA PAYLOAD LAB"

    def __init__(self):
        super().__init__()
        self._stop_event = threading.Event()
        self._active_thread: threading.Thread | None = None
        self._payloads_data: list[dict] = []
        self._last_payload: str = ""

    def compose(self) -> ComposeResult:
        with Horizontal():
            # --- Panel gauche : selecteur ---
            with Vertical(id="panel-left"):
                yield Static("LAB PAYLOADS", id="lbl-title")
                yield Select(
                    [("xss", "xss"), ("sqli", "sqli"), ("lfi", "lfi"),
                     ("rce", "rce"), ("ssti", "ssti"), ("ssrf", "ssrf"), ("mixed", "mixed")],
                    value="xss",
                    id="sel-category",
                )
                yield Select(
                    [("DIAMOND", "DIAMOND"), ("ELITE", "ELITE"),
                     ("VETERAN", "VETERAN"), ("ALL", "ALL")],
                    value="DIAMOND",
                    id="sel-rank",
                )
                yield Button("CHARGER PAYLOADS", id="btn-load")
                yield Static("0 payloads charges", id="lbl-count")
                yield ListView(id="payload-list")
                yield Button("TESTER SELECTION", id="btn-test")
                yield Button("SUPPRIMER FAILS", id="btn-purge")
                yield Button("STOP", id="btn-stop", variant="error")
                yield Static("", id="lbl-sep")
                yield Static("URL CUSTOM POUR TEST:", id="lbl-custom")
                yield Input(placeholder="http://cible.com/search?q=", id="custom-url")

            # --- Panel centre : console attaque ---
            with Vertical(id="panel-center"):
                yield RichLog(id="log-attack", markup=True, wrap=True)

            # --- Panel droit : analyse payload ---
            with Vertical(id="panel-right"):
                yield Static("Selectionnez un payload dans la liste", id="lbl-payload-detail")
                yield RichLog(id="log-result", markup=True, wrap=True)
                yield Static("--- ACTIONS ---", id="lbl-actions")
                yield Button("[COPIER PAYLOAD]", id="btn-copy")
                yield Button("[TESTER SUR URL CUSTOM]", id="btn-test-url")
                yield Button("[VOIR DANS NAVIGATEUR]", id="btn-browser")

    # -----------------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-load":
            self._do_load()
        elif bid == "btn-test":
            self._start_test()
        elif bid == "btn-purge":
            self._confirm_purge()
        elif bid == "btn-stop":
            self._stop_event.set()
            self.query_one("#log-attack", RichLog).write("[bold red]>>> STOP demande[/bold red]")
        elif bid == "btn-copy":
            self._copy_payload()
        elif bid == "btn-test-url":
            self._test_custom_url()
        elif bid == "btn-browser":
            self._open_in_browser()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        lv = self.query_one("#payload-list", ListView)
        idx = lv.index
        if idx is not None and 0 <= idx < len(self._payloads_data):
            self._show_detail(self._payloads_data[idx])

    # -----------------------------------------------------------------------
    # Load
    # -----------------------------------------------------------------------

    def _do_load(self) -> None:
        cat = str(self.query_one("#sel-category", Select).value)
        rank = str(self.query_one("#sel-rank", Select).value)
        payloads = _load_from_db(cat, rank)
        self._payloads_data = payloads

        lv = self.query_one("#payload-list", ListView)
        lv.clear()
        for p in payloads:
            lv.append(ListItem(Label(p["payload"][:26])))

        count_txt = f"{len(payloads)} payloads charges" if payloads else "aucun payload"
        self.query_one("#lbl-count", Static).update(count_txt)

        log = self.query_one("#log-attack", RichLog)
        if payloads:
            log.write(f"[bold green]>>> {len(payloads)} payloads [{cat.upper()} / {rank}][/bold green]")
        else:
            log.write(f"[yellow]>>> Aucun payload [{cat.upper()} / {rank}] â€” DB vide ou absente[/yellow]")

    # -----------------------------------------------------------------------
    # Detail + MiMo
    # -----------------------------------------------------------------------

    def _show_detail(self, p: dict) -> None:
        rank = p.get("rank", "?")
        rank_col = RANK_COLORS.get(rank, "#00ff41")
        waf = p.get("waf_score", 0)
        ptype = p.get("payload_type", "?")
        payload_text = p["payload"]

        detail = (
            f"[{rank_col}]RANG : {rank}[/{rank_col}]\n"
            f"TYPE : {ptype}\n"
            f"WAF  : {waf}/15\n"
            "---\n"
            f"{payload_text[:110]}"
        )
        self.query_one("#lbl-payload-detail", Static).update(detail)

        log = self.query_one("#log-result", RichLog)
        log.clear()
        log.write(f"\n[bold cyan]>>> ANALYSE : {payload_text[:55]}[/bold cyan]")
        log.write(f"[cyan]WAF bypasses : {waf}/15[/cyan]")
        log.write(f"[cyan]Rang         : {rank}[/cyan]")
        log.write(f"[cyan]Type         : {ptype}[/cyan]")

        # Impact description
        base_type = ptype.split('_')[0] if '_' in ptype else ptype
        impact = IMPACT_DESCRIPTIONS.get(base_type, IMPACT_DESCRIPTIONS.get('mixed', ''))
        log.write(f"\n[bold yellow]--- CE QUE CE PAYLOAD FAIT ---[/bold yellow]")
        log.write(f"[yellow]{impact}[/yellow]")

        log.write("\n[dim]Appel MiMo API en cours...[/dim]")

        threading.Thread(
            target=self._async_mimo, args=(payload_text, waf), daemon=True
        ).start()

    def _async_mimo(self, payload: str, waf: int) -> None:
        explanation = _call_mimo(payload)
        log = self.query_one("#log-result", RichLog)
        self.call_from_thread(log.write, "[green]--- Explication MiMo ---[/green]")
        self.call_from_thread(log.write, explanation)

        if waf >= 12:
            rec = "[bold green]GARDER â€” excellent bypass WAF[/bold green]"
        elif waf >= 7:
            rec = "[yellow]AMELIORER â€” bypass partiel[/yellow]"
        else:
            rec = "[bold red]SUPPRIMER â€” bypass insuffisant[/bold red]"
        self.call_from_thread(log.write, f"[bold]Recommandation : {rec}[/bold]")

    # -----------------------------------------------------------------------
    # Test
    # -----------------------------------------------------------------------

    def _start_test(self) -> None:
        if not self._payloads_data:
            self.query_one("#log-attack", RichLog).write("[yellow]Chargez d'abord des payloads.[/yellow]")
            return
        if self._active_thread and self._active_thread.is_alive():
            self.query_one("#log-attack", RichLog).write(
                "[yellow]Test deja en cours â€” appuyez STOP.[/yellow]"
            )
            return
        cat = str(self.query_one("#sel-category", Select).value)
        custom_url = str(self.query_one("#custom-url", Input).value or "").strip()
        self._stop_event.clear()
        self._active_thread = threading.Thread(
            target=self._run_test, args=(cat, list(self._payloads_data), custom_url), daemon=True
        )
        self._active_thread.start()

    def _run_test(self, category: str, payloads: list[dict], custom_url: str = “”) -> None:
        log = self.query_one(“#log-attack”, RichLog)
        use_custom = bool(custom_url)
        ep = ENDPOINTS.get(category, ENDPOINTS[“xss”])
        dvwa_url, param, method = ep[“url”], ep[“param”], ep[“method”]

        session = requests.Session()
        if use_custom:
            self.call_from_thread(
                log.write,
                f”[bold cyan]>>> ATTAQUE EN COURS : [{category.upper()}] contre [{custom_url[:50]}][/bold cyan]”
            )
        else:
            self.call_from_thread(
                log.write,
                f”[bold green]>>> ATTAQUE EN COURS : [{category.upper()}] contre [{DVWA_BASE}][/bold green]”
            )
            if not _dvwa_login(session):
                self.call_from_thread(
                    log.write, “[bold red]Login DVWA echoue — DVWA actif sur :8081 ?[/bold red]”
                )
                return
            self.call_from_thread(log.write, “[green]Login DVWA OK[/green]”)

        confirmed = blocked = inconclusive = 0

        for item in payloads:
            if self._stop_event.is_set():
                self.call_from_thread(log.write, “[red]>>> STOP[/red]”)
                break

            payload = item[“payload”]
            self._last_payload = payload

            try:
                t0 = time.time()
                if use_custom:
                    full_url = f”{custom_url}{payload}”
                    r = session.get(full_url, timeout=6, headers={“User-Agent”: “CYBERIA/1.0”})
                    display = f”[cyan]GET {full_url[:60]}[/cyan]”
                elif method == “POST”:
                    r = session.post(dvwa_url, data={param: payload, “Submit”: “Submit”}, timeout=6)
                    display = f”[cyan]POST ?{param}={payload[:34]}[/cyan]”
                else:
                    r = session.get(dvwa_url, params={param: payload}, timeout=6)
                    display = f”[cyan]GET ?{param}={payload[:34]}[/cyan]”
                elapsed = int((time.time() - t0) * 1000)

                verd, color = _verdict(r.status_code, r.text, payload)
                if verd == “CONFIRMED”:
                    confirmed += 1
                elif verd == “BLOCKED”:
                    blocked += 1
                else:
                    inconclusive += 1

                self.call_from_thread(
                    log.write,
                    f”{display} [{color}]{verd}[/{color}] [dim]{r.status_code} {elapsed}ms[/dim]”
                )

                if verd == “CONFIRMED”:
                    body_lower = r.text.lower()
                    extracted = [
                        sig for sig in [“first name”, “surname”, “gordonb”, “pablo”, “smithy”, “bob”]
                        if sig in body_lower
                    ]
                    if extracted:
                        self.call_from_thread(
                            log.write,
                            f”[bold green]  DATA: {', '.join(extracted)}[/bold green]”
                        )

            except requests.exceptions.ConnectionError:
                target_label = custom_url[:40] if use_custom else “DVWA”
                self.call_from_thread(log.write, f”[red]Connexion impossible a {target_label}[/red]”)
                break
            except Exception as exc:
                self.call_from_thread(log.write, f”[red]Erreur: {exc}[/red]”)

            time.sleep(1)

        self.call_from_thread(
            log.write,
            f”[bold green]>>> FIN {category.upper()} : “
            f”CONFIRMED={confirmed} BLOCKED={blocked} INCONCLUSIVE={inconclusive}[/bold green]”
        )

    # -----------------------------------------------------------------------
    # Purge
    # -----------------------------------------------------------------------

    def _confirm_purge(self) -> None:
        cat = str(self.query_one("#sel-category", Select).value)

        def on_dismiss(confirmed: bool) -> None:
            if confirmed:
                self._do_purge(cat)

        self.push_screen(
            ConfirmDialog(f"Supprimer les fails\n[{cat.upper()}] bypass_confirmed=0 ?"),
            on_dismiss,
        )

    def _do_purge(self, category: str) -> None:
        log = self.query_one("#log-attack", RichLog)
        if not DB_PATH.exists():
            log.write("[red]Base introuvable[/red]")
            return
        try:
            con = sqlite3.connect(str(DB_PATH), timeout=5)
            cur = con.execute(
                "DELETE FROM results WHERE bypass_confirmed=0 AND payload_type LIKE ?",
                (f"%{category}%",),
            )
            deleted = cur.rowcount
            con.commit()
            con.close()
            log.write(
                f"[bold green]>>> Purge OK : {deleted} entrees supprimees [{category.upper()}][/bold green]"
            )
        except Exception as exc:
            log.write(f"[red]Erreur purge: {exc}[/red]")

    # -----------------------------------------------------------------------
    # Actions : copier, tester URL custom, ouvrir navigateur
    # -----------------------------------------------------------------------

    def _get_selected_payload(self) -> str | None:
        lv = self.query_one("#payload-list", ListView)
        idx = lv.index
        if idx is not None and 0 <= idx < len(self._payloads_data):
            return self._payloads_data[idx]["payload"]
        return None

    def _copy_payload(self) -> None:
        payload = self._get_selected_payload()
        if not payload:
            self.query_one("#log-result", RichLog).write("[yellow]Selectionnez un payload d'abord[/yellow]")
            return
        try:
            import subprocess
            subprocess.run(['clip'], input=payload.encode('utf-8'), check=True, timeout=5)
            self.query_one("#log-result", RichLog).write(
                f"[bold green]>>> Payload copie dans le presse-papier ![/bold green]"
            )
        except Exception:
            # Fallback: ecrire dans un fichier
            try:
                Path(".cyberia/clipboard_payload.txt").write_text(payload, encoding='utf-8')
                self.query_one("#log-result", RichLog).write(
                    f"[yellow]Clipboard indisponible. Sauve dans .cyberia/clipboard_payload.txt[/yellow]"
                )
            except Exception as exc:
                self.query_one("#log-result", RichLog).write(f"[red]Erreur: {exc}[/red]")

    def _test_custom_url(self) -> None:
        payload = self._get_selected_payload()
        if not payload:
            self.query_one("#log-result", RichLog).write("[yellow]Selectionnez un payload d'abord[/yellow]")
            return
        custom_url = str(self.query_one("#custom-url", Input).value or "").strip()
        if not custom_url:
            self.query_one("#log-result", RichLog).write(
                "[yellow]Entrez une URL custom dans le champ en bas a gauche[/yellow]"
            )
            return
        # Construire l'URL finale
        if '?' in custom_url:
            full_url = custom_url + payload
        else:
            full_url = custom_url + '?' + payload

        log = self.query_one("#log-result", RichLog)
        log.write(f"\n[bold cyan]>>> TEST URL CUSTOM[/bold cyan]")
        log.write(f"[cyan]URL: {full_url[:120]}[/cyan]")

        threading.Thread(
            target=self._async_custom_url, args=(full_url, payload), daemon=True
        ).start()

    def _async_custom_url(self, url: str, payload: str) -> None:
        log = self.query_one("#log-result", RichLog)
        try:
            r = requests.get(url, timeout=10, headers={'User-Agent': 'CYBERIA/1.0'})
            verd, color = _verdict(r.status_code, r.text, payload)
            self.call_from_thread(
                log.write,
                f"[{color}]{verd}[/{color}] HTTP {r.status_code} | {len(r.text)} chars"
            )
            # Afficher un extrait
            body_lower = r.text.lower() if r.text else ''
            if payload.lower() in body_lower:
                self.call_from_thread(log.write, "[bold green]  PAYLOAD REFLECHI dans la reponse ![/bold green]")
            if verd == "CONFIRMED":
                self.call_from_thread(log.write, "[bold green]  >>> VULNERABILITE CONFIRMEE SUR URL CUSTOM[/bold green]")
        except requests.exceptions.ConnectionError:
            self.call_from_thread(log.write, "[red]Connexion impossible a l'URL[/red]")
        except Exception as exc:
            self.call_from_thread(log.write, f"[red]Erreur: {exc}[/red]")

    def _open_in_browser(self) -> None:
        payload = self._get_selected_payload()
        if not payload:
            self.query_one("#log-result", RichLog).write("[yellow]Selectionnez un payload d'abord[/yellow]")
            return
        custom_url = str(self.query_one("#custom-url", Input).value or "").strip()
        if not custom_url:
            # Utiliser DVWA par defaut
            cat = str(self.query_one("#sel-category", Select).value)
            ep = ENDPOINTS.get(cat, ENDPOINTS['xss'])
            base = ep['url']
            param = ep['param']
            if '?' in base:
                full_url = base + '&' + param + '=' + payload
            else:
                full_url = base + '?' + param + '=' + payload
        else:
            if '?' in custom_url:
                full_url = custom_url + payload
            else:
                full_url = custom_url + '?' + payload

        try:
            webbrowser.open(full_url)
            self.query_one("#log-result", RichLog).write(
                f"[bold magenta]>>> Navigateur ouvert : {full_url[:100]}[/bold magenta]"
            )
        except Exception as exc:
            self.query_one("#log-result", RichLog).write(f"[red]Erreur: {exc}[/red]")


if __name__ == "__main__":
    PayloadLabDashboard().run()

