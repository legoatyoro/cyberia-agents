"""
CYBERIA IA Autonome v18  Interface moderne Textual
3 panels : Stats/Menu | Chat | Logs Agents
"""
import os, sys, json, sqlite3
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.widgets import (Header, Footer, Input, Button, 
                              Label, RichLog, Static, ListView, ListItem)
from textual.reactive import reactive
from textual.timer import Timer
from textual import events

DB_LAB    = Path(".cyberia/payload_lab.db")
DB_MEM    = Path(".cyberia/memory_core.db")
LOG_EVOL  = Path(".cyberia/evolution_live.log")
LOG_RES   = Path(".cyberia/evolution_live.log")

CHAT_MODEL = os.getenv("CYBERIA_CHAT_MODEL", "xiaomi/mimo-v2.5-pro")

def get_lab_stats():
    if not DB_LAB.exists():
        return {"gen": 0, "diamond": 0, "bypasses": 0, "payloads": 0}
    try:
        conn = sqlite3.connect(DB_LAB)
        bypasses = conn.execute("SELECT COUNT(*) FROM results WHERE bypass_confirmed=1").fetchone()[0]
        payloads = conn.execute("SELECT COUNT(*) FROM imported_payloads").fetchone()[0]
        conn.close()
        return {"bypasses": bypasses, "payloads": payloads}
    except:
        return {"bypasses": 0, "payloads": 0}

def get_mem_stats():
    if not DB_MEM.exists():
        return 0
    try:
        conn = sqlite3.connect(DB_MEM)
        total = conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]
        conn.close()
        return total
    except:
        return 0

def get_last_log_lines(path, n=8):
    if not Path(path).exists():
        return ["[dim]En attente...[/dim]"]
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:] if lines else ["[dim]Vide[/dim]"]
    except:
        return ["[dim]Erreur lecture[/dim]"]

def call_cyberia(message):
    """Appelle CYBERIA via le router multi-modeles"""
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1"
        )
        # Charge contexte memoire (recherche semantique)
        mem_context = ""
        try:
            from core.memory_core import get_core
            results = get_core().search(message, top_k=5)
            if results:
                lines = []
                for r in results:
                    sim = r.get('similarity', 0)
                    if sim < 0.15:
                        continue
                    val = r.get('value', '')[:100]
                    key = r.get('key', '')[:40]
                    lines.append('[{}] {} : {}'.format(sim, key, val))
                mem_context = '\n'.join(lines)
        except Exception:
            pass

        stats = get_lab_stats()
        system = f"""Tu es CYBERIA, une IA autonome de cybersecurite offensive.
Tu tournes en local avec {get_mem_stats()} memories apprises.
Lab actif: {stats['bypasses']} bypasses confirmes, {stats['payloads']} payloads.
Providers actifs: OpenRouter (Claude Sonnet 4.6, DeepSeek, MiMo), Together AI (Llama 3.3).
Tu es directe, technique, en francais. Pas de markdown excessif.
Memoire recente: {mem_context[:300]}"""

        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": message}
            ],
            max_tokens=800
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"[ERREUR] {str(e)[:100]}"


CSS = """
Screen {
    background: #0a0a0a;
}

#left-panel {
    width: 28;
    background: #0d0d0d;
    border-right: solid #00ff41;
    padding: 0 1;
}

#chat-panel {
    background: #0a0a0a;
    border-right: solid #00ff41;
}

#right-panel {
    width: 36;
    background: #0d0d0d;
    padding: 0 1;
}

#stats-box {
    height: auto;
    background: #0d1a0d;
    border: solid #00ff41;
    margin-bottom: 1;
    padding: 0 1;
}

#menu-box {
    background: #0d0d0d;
    border: solid #1a3a1a;
    padding: 0 1;
}

#chat-log {
    background: #0a0a0a;
    border: none;
    padding: 0 1;
    height: 1fr;
}

#input-bar {
    height: 3;
    background: #0d0d0d;
    border-top: solid #00ff41;
    padding: 0 1;
}

#chat-input {
    background: #0a0a0a;
    color: #00ff41;
    border: solid #1a3a1a;
    width: 1fr;
}

#send-btn {
    background: #003300;
    color: #00ff41;
    border: solid #00ff41;
    width: 10;
    margin-left: 1;
}

#send-btn:hover {
    background: #00ff41;
    color: #000000;
}

#evol-log {
    height: 1fr;
    border: solid #1a3a1a;
    background: #0a0f0a;
    margin-bottom: 1;
}

#res-log {
    height: 1fr;
    border: solid #1a1a3a;
    background: #0a0a0f;
}

.panel-title {
    color: #00ff41;
    text-style: bold;
    margin-bottom: 1;
}

.stat-line {
    color: #00cc33;
}

.menu-item {
    color: #008822;
    margin-left: 1;
}

.menu-item:hover {
    color: #00ff41;
    text-style: bold;
}

Header {
    background: #001100;
    color: #00ff41;
    text-style: bold;
}

Footer {
    background: #001100;
    color: #00cc33;
}
"""

class CyberiaV18(App):
    CSS = CSS
    TITLE = "CYBERIA IA Autonome v18"
    BINDINGS = [
        ("ctrl+c", "quit", "Quitter"),
        ("ctrl+l", "clear_chat", "Effacer chat"),
        ("ctrl+r", "refresh_stats", "Refresh"),
        ("f1", "agent_status", "Statut agents"),
        ("f2", "valhalla_report", "Rapport Valhalla"),
    ]

    gen_count    = reactive(0)
    bypass_count = reactive(0)
    mem_count    = reactive(0)
    is_thinking  = reactive(False)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            # PANEL GAUCHE  Stats + Menu
            with Vertical(id="left-panel"):
                yield Static(" CYBERIA v18", classes="panel-title")
                yield Static(id="stats-box")
                yield Static(" ACTIONS ", classes="panel-title")
                with Vertical(id="menu-box"):
                    yield Button(" Valhalla", id="btn-valhalla", variant="default")
                    yield Button(" Lab Stats", id="btn-lab", variant="default")
                    yield Button(" Memoire", id="btn-mem", variant="default")
                    yield Button(" AgentCoder", id="btn-coder", variant="default")
                    yield Button(" Providers", id="btn-providers", variant="default")

            # PANEL CENTRE  Chat
            with Vertical(id="chat-panel"):
                yield RichLog(id="chat-log", highlight=True, markup=True, wrap=True)
                with Horizontal(id="input-bar"):
                    yield Input(placeholder="/web /lire /code ou question libre...", id="chat-input")
                    yield Button("SEND", id="send-btn")

            # PANEL DROIT  Logs agents
            with Vertical(id="right-panel"):
                yield Static(" EVOLUTION LAB", classes="panel-title")
                yield RichLog(id="evol-log", highlight=True, markup=True, wrap=True)
                yield Static(" RESEARCH CREW", classes="panel-title")
                yield RichLog(id="res-log", highlight=True, markup=True, wrap=True)

        yield Footer()

    def on_mount(self) -> None:
        self.refresh_stats()
        self.refresh_logs()
        self.chat_welcome()
        # Refresh auto toutes les 10s
        self.set_interval(10, self.refresh_stats)
        self.set_interval(5, self.refresh_logs)

    def chat_welcome(self):
        log = self.query_one("#chat-log", RichLog)
        log.write("[bold green] CYBERIA v18  IA Autonome[/bold green]")
        log.write(f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim] Systeme pret.")
        log.write("")
        log.write("[dim]Commandes: /valhalla /lab /mem /coder /providers[/dim]")
        log.write("[dim]Ou pose une question directement a CYBERIA.[/dim]")
        log.write("" * 40)

    def refresh_stats(self):
        stats = get_lab_stats()
        mem   = get_mem_stats()

        # Lire derniere gen depuis log
        last_gen = "?"
        if LOG_EVOL.exists():
            try:
                lines = LOG_EVOL.read_text(encoding="utf-8", errors="replace").splitlines()
                for l in reversed(lines):
                    if "[GEN " in l:
                        import re
                        m = re.search(r"\[GEN (\d+)\]", l)
                        if m:
                            last_gen = m.group(1)
                            break
            except:
                pass

        # Provider status
        from dotenv import load_dotenv
        load_dotenv(override=True)
        import dotenv as _denv; _denv.load_dotenv(override=True)
        or_ok  = "OK" if os.getenv("OPENROUTER_API_KEY") else "XX"
        tog_ok = "OK" if os.getenv("TOGETHER_API_KEY")   else "XX"
        ds_ok  = "OK" if os.getenv("DEEPSEEK_API_KEY")   else "XX"

        box = self.query_one("#stats-box", Static)
        box.update(
            f"[bold green] LAB STATUS [/bold green]\n"
            f"[green]GEN      :[/green] [white]{last_gen}[/white]\n"
            f"[green]Bypasses :[/green] [white]{stats['bypasses']:,}[/white]\n"
            f"[green]Payloads :[/green] [white]{stats['payloads']:,}[/white]\n"
            f"[green]Memoire  :[/green] [white]{mem:,}[/white]\n"
            f"\n[bold green] PROVIDERS [/bold green]\n"
            f"[green]OpenRouter:[/green] {or_ok}\n"
            f"[green]Together  :[/green] {tog_ok}\n"
            f"[green]DeepSeek  :[/green] {ds_ok}\n"
        )

    def refresh_logs(self):
        # Evol log
        evol = self.query_one("#evol-log", RichLog)
        evol.clear()
        for line in get_last_log_lines(LOG_EVOL, 12):
            if "BYPASS" in line:
                evol.write(f"[bold green]{line}[/bold green]")
            elif "BLOQUE" in line:
                evol.write(f"[dim red]{line}[/dim red]")
            elif "GEN" in line:
                evol.write(f"[bold yellow]{line}[/bold yellow]")
            else:
                evol.write(f"[dim]{line}[/dim]")

        # Research log  depuis DB
        res = self.query_one("#res-log", RichLog)
        res.clear()
        try:
            import sqlite3 as _sq
            conn = _sq.connect(".cyberia/research_crew.db")
            rows = conn.execute("SELECT agent, category, content FROM discoveries ORDER BY rowid DESC LIMIT 8").fetchall()
            conn.close()
            for row in rows:
                agent, cat, content = row
                preview = content[:60].replace("\n", " ")
                if cat == "cve_pattern":
                    res.write(f"[red][{agent[:10]}][/red] {preview}")
                elif cat == "algorithm":
                    res.write(f"[cyan][{agent[:10]}][/cyan] {preview}")
                elif cat == "conversation":
                    res.write(f"[green][{agent[:10]}][/green] {preview}")
                else:
                    res.write(f"[dim][{agent[:10]}][/dim] {preview}")
        except Exception as e:
            res.write(f"[dim]DB: {str(e)[:50]}[/dim]")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.handle_message(event.value)
        event.input.value = ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "send-btn":
            inp = self.query_one("#chat-input", Input)
            self.handle_message(inp.value)
            inp.value = ""
        elif btn_id == "btn-valhalla":
            self.handle_message("/valhalla")
        elif btn_id == "btn-lab":
            self.handle_message("/lab")
        elif btn_id == "btn-mem":
            self.handle_message("/mem")
        elif btn_id == "btn-coder":
            self.handle_message("/coder aide moi a analyser les bypasses DIAMOND")
        elif btn_id == "btn-providers":
            self.handle_message("/providers")

    def handle_message(self, text: str) -> None:
        if not text.strip():
            return
        log = self.query_one("#chat-log", RichLog)
        ts  = datetime.now().strftime("%H:%M:%S")
        log.write(f"\n[bold cyan][{ts}] Yoro >[/bold cyan] {text}")

        # Commandes internes
        if text.startswith("/valhalla"):
            self.cmd_valhalla(log)
        elif text.startswith("/lab"):
            self.cmd_lab(log)
        elif text.startswith("/mem"):
            self.cmd_mem(log)
        elif text.startswith("/providers"):
            self.cmd_providers(log)
        elif text.startswith("/coder "):
            task = text[7:]
            log.write("[yellow]AgentCoder en cours...[/yellow]")
            self.run_worker(self.worker_coder(task, log))
        else:
            log.write("[dim yellow]CYBERIA reflechit...[/dim yellow]")
            self.run_worker(self.worker_chat(text, log))

    async def worker_chat(self, text, log):
        import asyncio
        resp = await asyncio.get_event_loop().run_in_executor(None, call_cyberia, text)
        ts   = datetime.now().strftime("%H:%M:%S")
        log.write(f"\n[bold green][{ts}] CYBERIA >[/bold green]")
        for line in resp.splitlines():
            log.write(f"  {line}")
        log.write("" * 40)

    async def worker_coder(self, task, log):
        import asyncio
        sys.path.insert(0, str(Path(__file__).parent))
        from agents.agent_coder import run_task
        result = await asyncio.get_event_loop().run_in_executor(None, run_task, task)
        ts = datetime.now().strftime("%H:%M:%S")
        if result["success"]:
            log.write(f"[bold green][{ts}] AgentCoder OK ({result['iterations']} iter)[/bold green]")
            for line in result["output"].splitlines()[:20]:
                log.write(f"  {line}")
        else:
            log.write(f"[red][{ts}] AgentCoder ECHEC: {result.get('error','?')[:100]}[/red]")
        log.write("" * 40)

    def cmd_valhalla(self, log):
        stats = get_lab_stats()
        log.write(f"\n[bold green] VALHALLA REPORT[/bold green]")
        log.write(f"  Bypasses confirmes : [white]{stats['bypasses']:,}[/white]")
        log.write(f"  Payloads total     : [white]{stats['payloads']:,}[/white]")
        try:
            conn = sqlite3.connect(DB_LAB)
            top = conn.execute(
                "SELECT payload_type, COUNT(*) as n FROM results WHERE bypass_confirmed=1 "
                "GROUP BY payload_type ORDER BY n DESC LIMIT 5"
            ).fetchall()
            conn.close()
            log.write("  Top types:")
            for t in top:
                log.write(f"    [green]{t[0]:15}[/green] {t[1]:>6} bypasses")
        except Exception as e:
            log.write(f"  [red]Erreur: {e}[/red]")
        log.write("" * 40)

    def cmd_lab(self, log):
        last_lines = get_last_log_lines(LOG_EVOL, 5)
        log.write(f"\n[bold yellow] LAB  Derniere activite[/bold yellow]")
        for l in last_lines:
            log.write(f"  {l}")
        log.write("" * 40)

    def cmd_mem(self, log):
        mem = get_mem_stats()
        log.write(f"\n[bold blue] MEMOIRE CYBERIA[/bold blue]")
        log.write(f"  Total items : [white]{mem:,}[/white]")
        try:
            conn = sqlite3.connect(DB_MEM)
            cats = conn.execute(
                "SELECT source, COUNT(*) as n FROM memory_items "
                "GROUP BY source ORDER BY n DESC LIMIT 6"
            ).fetchall()
            conn.close()
            for c in cats:
                log.write(f"  [green]{c[0][:30]:30}[/green] {c[1]:>5}")
        except Exception as e:
            log.write(f"  [red]Erreur: {e}[/red]")
        log.write("" * 40)

    def cmd_providers(self, log):
        log.write(f"\n[bold] PROVIDERS API[/bold]")
        providers = [
            ("OpenRouter", "OPENROUTER_API_KEY", "Claude Sonnet / DeepSeek / MiMo"),
            ("Together AI", "TOGETHER_API_KEY",  "Llama 3.3 70B"),
            ("DeepSeek",   "DEEPSEEK_API_KEY",   "deepseek-chat (fallback)"),
            ("Groq",       "GROQ_API_KEY",        "Llama rapide (monitoring)"),
            ("Mistral",    "MISTRAL_API_KEY",     "mistral-small (doc/fr)"),
        ]
        for name, env, models in providers:
            ok  = "" if os.getenv(env) else ""
            log.write(f"  {ok} [green]{name:12}[/green] {models}")
        log.write("" * 40)

    def action_clear_chat(self):
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        self.chat_welcome()

    def action_refresh_stats(self):
        self.refresh_stats()
        self.refresh_logs()

    def action_agent_status(self):
        self.handle_message("/providers")

    def action_valhalla_report(self):
        self.handle_message("/valhalla")


if __name__ == "__main__":
    app = CyberiaV18()
    app.run()


