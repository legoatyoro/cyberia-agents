# -*- coding: utf-8 -*-
"""
core/scan_api.py — Serveur Flask avec SSE pour le dashboard de scan.

Usage:
  python core/scan_api.py
  python core/scan_api.py --port 5050 --host 0.0.0.0
"""
import json
import queue
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

try:
    from flask import Flask, request, Response, jsonify, send_file
except ImportError:
    print("[!] flask non installe. pip install flask")
    raise SystemExit(1)

from core.auto_scanner import (
    AutoScanner, ALL_CATEGORIES, CYBERIA_DIR,
    dvwa_login, _empty_stats, RATE_LIMIT_SEC, TIMEOUT,
    _send_get, _send_post, _simple_analyze,
)

try:
    from core.waf_fingerprint import fingerprint_waf, learn_from_response
    _WAF_AVAIL = True
except Exception:
    _WAF_AVAIL = False

try:
    from core.pentest_runner import (
        send_payload, analyze_response, validate_exploitation, save_proof,
    )
    _RUNNER_AVAIL = True
except Exception:
    _RUNNER_AVAIL = False
    def validate_exploitation(cat, body, payload):
        return {'confirmed': False, 'proof': '', 'evidence': ''}
    def save_proof(cat, payload, body, **kw):
        return ''

PROOFS_DIR = CYBERIA_DIR / "proofs"
SCAN_RESULTS_DIR = CYBERIA_DIR / "scan_results"
DASHBOARD_HTML = Path(__file__).parent / "scan_dashboard.html"

_CAT_PROOF_TYPE = {
    'sqli': 'SQLI_DATA_LEAKED',
    'lfi':  'LFI_FILE_READ',
    'rce':  'RCE_COMMAND_OUTPUT',
    'xss':  'XSS_REFLECTED',
    'ssti': 'SSTI_EVALUATED',
    'ssrf': 'SSRF_INTERNAL_ACCESS',
}

app = Flask(__name__)
_scans: dict = {}
_scans_lock = threading.Lock()


# ---------------------------------------------------------------------------
# StreamingScanner
# ---------------------------------------------------------------------------

class StreamingScanner(AutoScanner):
    """AutoScanner instrumenté pour émettre des events SSE dans une queue."""

    def __init__(self, url: str, event_queue: queue.Queue, target_name: str = ""):
        super().__init__(url, target_name)
        self._q = event_queue
        self.report_path = None

    def _emit(self, event_type: str, data: dict) -> None:
        try:
            self._q.put_nowait(json.dumps({"type": event_type, "data": data}))
        except queue.Full:
            pass

    def scan_category(self, category: str, payloads=None) -> dict:
        if payloads is None:
            payloads = self._load_payloads(category)

        if not payloads:
            return _empty_stats(category)

        endpoint = {**self.endpoint_base, "vuln_type": category}
        use_post = category == "rce" and "exec" in self.path
        if use_post:
            endpoint["method"] = "POST"

        stats = _empty_stats(category)

        for payload in payloads:
            if _RUNNER_AVAIL:
                try:
                    status, body, headers, elapsed_ms, error = send_payload(
                        self.target, endpoint, payload, self.session
                    )
                except Exception as exc:
                    status, body, headers, elapsed_ms, error = 0, "", {}, 0, str(exc)
            else:
                fn = _send_post if use_post else _send_get
                param = "ip" if use_post else self.param_name
                status, body, headers, elapsed_ms, error = fn(
                    self.session, self.base_url + self.path, param, payload
                )

            if error and status == 0:
                stats["errors"] += 1
                self._emit("payload_tested", {
                    "category": category, "payload": payload[:80],
                    "status": "ERROR", "http_code": 0, "ms": 0,
                    "evidence": error[:60],
                })
                continue

            if _RUNNER_AVAIL:
                try:
                    result = analyze_response(status, body, headers, elapsed_ms, category, payload)
                except Exception:
                    result = _simple_analyze(status, body, payload, category)
            else:
                result = _simple_analyze(status, body, payload, category)

            verdict = result["verdict"]
            evidence = result["evidence"]
            stats["total"] += 1

            self._emit("payload_tested", {
                "category": category,
                "payload": payload[:80],
                "status": verdict,
                "http_code": status,
                "ms": elapsed_ms,
                "evidence": evidence[:80],
            })

            val = validate_exploitation(category, body, payload)
            if val["confirmed"]:
                proof_path = save_proof(
                    category, payload, body,
                    url=self.base_url + self.path,
                    status_code=status,
                    elapsed_ms=elapsed_ms,
                    proof_type=val["proof"],
                )
                self._emit("proof_found", {
                    "category": category,
                    "proof_type": val["proof"],
                    "evidence": val["evidence"][:120],
                    "file": Path(proof_path).name if proof_path else "",
                    "payload": payload[:80],
                })

            if verdict in ("CONFIRMED", "LIKELY"):
                stats["confirmed"] += 1
                stats["hits"].append({
                    "payload": payload, "evidence": evidence,
                    "status": status, "elapsed_ms": elapsed_ms,
                    "proof": val["proof"], "exploit_evidence": val["evidence"],
                })
            elif verdict == "BLOCKED":
                stats["blocked"] += 1
            else:
                stats["inconclusive"] += 1

            if _WAF_AVAIL:
                try:
                    learn_from_response(
                        url=self.base_url + self.path,
                        payload=payload, status_code=status,
                        response_headers=headers,
                        waf_name=self.waf_result.get("waf", "unknown"),
                        payload_type=category, verdict=verdict,
                    )
                except Exception:
                    pass

        total = stats["total"]
        not_blocked = stats["confirmed"] + stats["inconclusive"]
        stats["bypass_rate"] = round(not_blocked / total * 100, 1) if total > 0 else 0.0
        return stats

    def run(self, categories=None, adapt=False) -> dict:
        from datetime import timezone
        self.scan_start = datetime.now(timezone.utc).isoformat()
        cats = categories or list(ALL_CATEGORIES)

        if _WAF_AVAIL:
            self.waf_result = fingerprint_waf(self.url)
        else:
            self.waf_result = {"waf": "unknown", "confidence": 0, "signatures": []}

        self._emit("waf_detected", {
            "waf": self.waf_result["waf"],
            "confidence": self.waf_result["confidence"],
            "signatures": self.waf_result.get("signatures", [])[:4],
        })

        if "localhost" in self.url or "127.0.0.1" in self.url:
            self.session = dvwa_login(self.base_url)

        for cat in cats:
            self._emit("category_start", {"category": cat})
            stats = self.scan_category(cat)
            self.results[cat] = stats
            self._emit("category_done", {
                "category": cat,
                "confirmed": stats["confirmed"],
                "blocked": stats["blocked"],
                "total": stats["total"],
                "bypass_rate": stats["bypass_rate"],
            })

        self.report_path = self.generate_report()
        summary = self._build_summary()
        self._emit("scan_complete", {
            "summary": summary,
            "report_path": self.report_path,
        })
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        return self.results


# ---------------------------------------------------------------------------
# Flask endpoints
# ---------------------------------------------------------------------------

@app.after_request
def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/")
def dashboard():
    if DASHBOARD_HTML.exists():
        return send_file(str(DASHBOARD_HTML))
    return "<h1>scan_dashboard.html introuvable</h1>", 404


@app.route("/api/scan/start", methods=["POST", "OPTIONS"])
def scan_start():
    if request.method == "OPTIONS":
        return Response(status=200)

    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url requis"}), 400

    categories = [c.lower() for c in (data.get("categories") or [])
                  if c.lower() in ALL_CATEGORIES]
    if not categories:
        categories = list(ALL_CATEGORIES)

    scan_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue(maxsize=1000)

    with _scans_lock:
        _scans[scan_id] = {
            "id": scan_id, "url": url, "categories": categories,
            "status": "running", "queue": q,
            "report_path": None,
            "started_at": datetime.utcnow().isoformat(),
        }

    def _run():
        try:
            scanner = StreamingScanner(url=url, event_queue=q)
            scanner.run(categories=categories, adapt=False)
            with _scans_lock:
                if scan_id in _scans:
                    _scans[scan_id]["report_path"] = scanner.report_path
                    _scans[scan_id]["status"] = "done"
        except Exception as exc:
            try:
                q.put_nowait(json.dumps({"type": "error", "data": {"message": str(exc)}}))
                q.put_nowait(None)
            except queue.Full:
                pass
            with _scans_lock:
                if scan_id in _scans:
                    _scans[scan_id]["status"] = "error"

    threading.Thread(target=_run, daemon=True, name=f"scan-{scan_id[:8]}").start()
    return jsonify({"scan_id": scan_id, "url": url, "categories": categories})


@app.route("/api/scan/stream/<scan_id>")
def scan_stream(scan_id):
    with _scans_lock:
        scan = _scans.get(scan_id)
    if not scan:
        return jsonify({"error": "scan_id inconnu"}), 404

    q = scan["queue"]

    def generate():
        yield "retry: 2000\n\n"
        while True:
            try:
                msg = q.get(timeout=25)
                if msg is None:
                    yield 'data: {"type":"end"}\n\n'
                    return
                yield f"data: {msg}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/scan/report/<scan_id>")
def scan_report(scan_id):
    with _scans_lock:
        scan = _scans.get(scan_id)
    if not scan:
        return jsonify({"error": "scan_id inconnu"}), 404

    rp = scan.get("report_path")
    if rp:
        p = Path(rp)
        if p.exists():
            return jsonify(json.loads(p.read_text(encoding="utf-8")))

    if SCAN_RESULTS_DIR.exists():
        reports = sorted(SCAN_RESULTS_DIR.glob("*.json"),
                         key=lambda f: f.stat().st_mtime, reverse=True)
        if reports:
            return jsonify(json.loads(reports[0].read_text(encoding="utf-8")))

    return jsonify({"status": scan.get("status", "unknown"), "message": "rapport en cours"}), 202


@app.route("/api/scan/proofs")
def scan_proofs():
    PROOFS_DIR.mkdir(parents=True, exist_ok=True)
    proofs = []
    for p in sorted(PROOFS_DIR.glob("*_proof.html"),
                    key=lambda f: f.stat().st_mtime, reverse=True):
        stem = p.name.replace("_proof.html", "")
        parts = stem.split("_")
        category = parts[3].lower() if len(parts) >= 4 else "unknown"
        proofs.append({
            "file":       p.name,
            "url":        f"/api/scan/proof/{p.name}",
            "category":   category,
            "proof_type": _CAT_PROOF_TYPE.get(category, "CONFIRMED"),
            "size_kb":    round(p.stat().st_size / 1024, 1),
            "mtime":      datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
        })
    return jsonify(proofs)


@app.route("/api/scan/proof/<path:filename>")
def serve_proof(filename):
    proof_path = (PROOFS_DIR / filename).resolve()
    try:
        proof_path.relative_to(PROOFS_DIR.resolve())
    except ValueError:
        return "forbidden", 403
    if not proof_path.exists() or proof_path.suffix != ".html":
        return "not found", 404
    return send_file(str(proof_path))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CYBERIA Scan API — Flask SSE")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    print(f"\n[CYBERIA] Scan API  → http://{args.host}:{args.port}/api/scan/")
    print(f"[CYBERIA] Dashboard → http://{args.host}:{args.port}/\n")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
