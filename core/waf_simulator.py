import re
import html
from urllib.parse import unquote

def normalize_payload(payload):
    """Decode payload in multiple passes: URL, IIS %uXXXX, \\uXXXX/\\xXX escapes, HTML entities.
    Returns list of all unique decoded forms (raw + each decoded stage).
    Stops when a pass produces no change or after 4 iterations."""
    forms = [payload]
    current = payload

    for _ in range(4):
        prev = current

        # URL decode — handles %3C, %253C (double-encoded), etc.
        try:
            step = unquote(current, encoding='utf-8', errors='replace')
        except Exception:
            step = current

        # IIS-style %uXXXX unicode
        step = re.sub(r'%u([0-9a-fA-F]{4})',
                      lambda m: chr(int(m.group(1), 16)), step)

        # Backslash unicode/hex escapes: <  \x3c
        step = re.sub(r'\\u([0-9a-fA-F]{4})',
                      lambda m: chr(int(m.group(1), 16)), step)
        step = re.sub(r'\\x([0-9a-fA-F]{2})',
                      lambda m: chr(int(m.group(1), 16)), step)

        # HTML entities: &lt; &#60; &#x3c; &amp; etc.
        try:
            step = html.unescape(step)
        except Exception:
            pass

        current = step
        if current not in forms:
            forms.append(current)
        if current == prev:
            break

    return forms

_COMMON_RULES = [
    # SQLi — keywords standalone
    (r'(\bUNION\b|\bSELECT\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bDROP\b|\bEXEC\b|\bEXECUTE\b)', 'SQLI-KEYWORD'),
    (r'(--|#|/\*|\*/|;\s*--)', 'SQLI-COMMENT'),
    (r'(\bOR\b|\bAND\b)\s+[\d\'"]+\s*=\s*[\d\'"]+', 'SQLI-BOOLEAN'),
    (r'(SLEEP|BENCHMARK|WAITFOR|PG_SLEEP)\s*\(', 'SQLI-TIMEBASED'),
    (r'(LOAD_FILE|INTO\s+OUTFILE|INTO\s+DUMPFILE)', 'SQLI-FILEOP'),
    # SSTI — all template syntaxes
    (r'\{\{.*\}\}', 'SSTI-JINJA2'),
    (r'\{%.*%\}', 'SSTI-JINJA2-BLOCK'),
    (r'\$\{.*\}', 'SSTI-EL'),
    (r'#\{.*\}', 'SSTI-RUBY'),
    (r'<%.*%>', 'SSTI-JSP'),
    (r'@\{.*\}', 'SSTI-THYMELEAF'),
    # LFI — path traversal all variants
    (r'(\.\./|\.\.\\|%2e%2e%2f|%252e%252e)', 'LFI-TRAVERSAL'),
    (r'(etc/passwd|etc/shadow|proc/self|windows/system32)', 'LFI-SENSITIVE'),
    (r'(php://|file://|data://|expect://|zip://)', 'LFI-WRAPPER'),
    # RCE — command execution
    (r'(;|\||`|\$\()\s*(cat|ls|whoami|id|wget|curl|bash|sh|cmd|powershell)', 'RCE-CMD'),
    (r'(system|exec|shell_exec|passthru|popen)\s*\(', 'RCE-PHP'),
    # XSS avance — HTML5 event handlers (OWASP CRS 941xxx)
    (r'\bon(pointer(over|enter|leave|down|up|move|cancel|out)|toggle|animationend|animationstart|animationiteration)\s*=', 'XSS-HTML5-EVENT'),
    (r'\bon(auxclick|beforeinput|compositionend|compositionstart|compositionupdate|contextmenu|copy|cut|paste)\s*=', 'XSS-HTML5-CLIPBOARD'),
    (r'\bon(drag(start|end|enter|leave|over|exit)?|drop)\s*=', 'XSS-HTML5-DRAG'),
    (r'\bon(fullscreenchange|fullscreenerror|gotpointercapture|lostpointercapture|securitypolicyviolation)\s*=', 'XSS-HTML5-MISC'),
    # XSS avance — SVG attacks
    (r'<svg[^>]*>', 'XSS-SVG-TAG'),
    (r'<svg.*?\bon\w+\s*=', 'XSS-SVG-EVENT'),
    (r'<use\s[^>]*xlink:href', 'XSS-SVG-USE'),
    (r'<animate[^>]*attributename\s*=\s*["\']?href', 'XSS-SVG-ANIMATE'),
    # XSS avance — meta refresh / base tag hijacking
    (r'<meta[^>]+http-equiv\s*=\s*["\']?refresh', 'XSS-META-REFRESH'),
    (r'<meta[^>]+content\s*=\s*["\']?\d+\s*;\s*url\s*=', 'XSS-META-REDIRECT'),
    (r'<base\s[^>]*href\s*=', 'XSS-BASE-HIJACK'),
    # SQLi avance — stacked queries (OWASP CRS 942xxx)
    (r';\s*(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC)', 'SQLI-STACKED'),
    (r';\s*WAITFOR\s+DELAY', 'SQLI-STACKED-MSSQL'),
    (r';\s*BEGIN\s+', 'SQLI-STACKED-BEGIN'),
    # SQLi avance — error-based
    (r'(extractvalue|updatexml|exp\s*\(\s*~|geometrycollection\s*\(|polygon\s*\(|linestring\s*\(|multipoint\s*\()', 'SQLI-ERROR-BASED'),
    (r'(floor\s*\(\s*rand|group\s+by.+having)', 'SQLI-ERROR-FLOOR'),
    # SQLi avance — out-of-band
    (r'(load_file\s*\(\s*[\'"]\\\\\\\\|utl_http\.|utl_file\.|httpuritype)', 'SQLI-OOB'),
    (r'(xp_dirtree|xp_fileexist|xp_cmdshell|sp_oacreate)', 'SQLI-MSSQL-OOB'),
    # Header injection — CRLF (OWASP CRS 943xxx)
    (r'(%0d%0a|%0a%0d|\r\n|\n\r|\\r\\n)', 'HEADER-CRLF'),
    (r'(%0d|%0a|\r|\n).*(set-cookie|location|content-type|x-forwarded)', 'HEADER-INJECT'),
    # Open redirect (OWASP CRS 934xxx)
    (r'(https?://|//)[a-z0-9\-\.]+\.[a-z]{2,}/', 'REDIRECT-EXTERNAL'),
    (r'(url\s*=\s*|redirect\s*=\s*|next\s*=\s*|return\s*=\s*)(https?://|//)', 'REDIRECT-PARAM'),
    (r'(\/\\|\/\/[^/])', 'REDIRECT-SLASH'),
]

WAF_PROFILES = {
    'cloudflare': {
        'name': 'Cloudflare WAF',
        'rules': [
            (r'<script[\s>]', 'CF-XSS-001'),
            (r'javascript\s*:', 'CF-XSS-002'),
            (r'on\w+\s*=', 'CF-XSS-003'),
            (r'union\s+select', 'CF-SQLI-001'),
            (r'or\s+1\s*=\s*1', 'CF-SQLI-002'),
            (r'\.\./\.\.|%2e%2e', 'CF-LFI-001'),
            (r'\$\{jndi:', 'CF-LOG4J-001'),
        ] + _COMMON_RULES
    },
    'aws_waf': {
        'name': 'AWS WAF',
        'rules': [
            (r'<script', 'AWS-XSS-01'),
            (r'onerror\s*=', 'AWS-XSS-02'),
            (r'union.*select', 'AWS-SQLI-01'),
            (r'\.\./\.\./\.\./', 'AWS-LFI-01'),
            (r'etc/passwd', 'AWS-LFI-02'),
        ] + _COMMON_RULES
    },
    'imperva': {
        'name': 'Imperva SecureSphere',
        'rules': [
            (r'<[^>]*script', 'IMP-XSS-100'),
            (r'javascript:', 'IMP-XSS-101'),
            (r'vbscript:', 'IMP-XSS-102'),
            (r'union\s+all\s+select', 'IMP-SQLI-200'),
            (r'sleep\s*\(', 'IMP-SQLI-202'),
            (r'\{\{.*\}\}', 'IMP-SSTI-301'),
        ] + _COMMON_RULES
    },
    'sucuri': {
        'name': 'Sucuri WAF',
        'rules': [
            (r'<script.*?>.*?</script>', 'SUC-XSS-01'),
            (r'alert\s*\(', 'SUC-XSS-02'),
            (r'document\.cookie', 'SUC-XSS-03'),
            (r'select.*from.*where', 'SUC-SQLI-01'),
            (r'drop\s+table', 'SUC-SQLI-03'),
            (r'/etc/passwd', 'SUC-LFI-01'),
        ] + _COMMON_RULES
    },
    'akamai': {
        'name': 'Akamai Kona',
        'rules': [
            (r'<\s*script', 'AKA-XSS-1001'),
            (r'on(load|error|click)\s*=', 'AKA-XSS-1002'),
            (r'(\bunion\b.+\bselect\b)', 'AKA-SQLI-2001'),
            (r'\$\{jndi:', 'AKA-LOG4J-4001'),
        ] + _COMMON_RULES
    },
    'f5_bigip': {
        'name': 'F5 BIG-IP ASM',
        'rules': [
            (r'<script', 'F5-XSS-001'),
            (r'javascript:', 'F5-XSS-002'),
            (r'onerror=', 'F5-XSS-003'),
            (r'union.*select.*from', 'F5-SQLI-001'),
            (r'1\s*=\s*1', 'F5-SQLI-002'),
            (r'\.\./\.\./\.\./\.\.[./]', 'F5-LFI-001'),
            (r'\{\{', 'F5-SSTI-001'),
        ] + _COMMON_RULES
    },
    'fortinet': {
        'name': 'Fortinet FortiWeb',
        'rules': [
            (r'<\s*script\s*>', 'FW-XSS-001'),
            (r'javascript\s*:', 'FW-XSS-002'),
            (r'UNION\s+SELECT', 'FW-SQLI-001'),
            (r"OR\s+'?\d+'?\s*=\s*'?\d+", 'FW-SQLI-002'),
            (r'etc/passwd', 'FW-LFI-001'),
            (r'php://filter', 'FW-LFI-002'),
        ] + _COMMON_RULES
    },
    'barracuda': {
        'name': 'Barracuda WAF',
        'rules': [
            (r'<script', 'BAR-XSS-01'),
            (r'on\w+=', 'BAR-XSS-02'),
            (r'alert\(', 'BAR-XSS-03'),
            (r'union\s+select', 'BAR-SQLI-01'),
            (r"'\s*or\s*'", 'BAR-SQLI-02'),
            (r'\.\.[/\\]', 'BAR-LFI-01'),
        ] + _COMMON_RULES
    },
    'wallarm': {
        'name': 'Wallarm WAF',
        'rules': [
            (r'<script[\s/>]', 'WAL-XSS-01'),
            (r'javascript:', 'WAL-XSS-02'),
            (r'union\s+(all\s+)?select', 'WAL-SQLI-01'),
            (r'sleep\s*\(\s*\d+', 'WAL-SQLI-02'),
            (r'\.\./\.\./\.\.[./]', 'WAL-LFI-01'),
            (r'\$\{', 'WAL-SSTI-01'),
        ] + _COMMON_RULES
    },
    'nginx_modsec': {
        'name': 'Nginx ModSecurity CRS',
        'rules': [
            (r'<script', 'MODSEC-941100'),
            (r'onerror\s*=', 'MODSEC-941110'),
            (r'javascript:', 'MODSEC-941120'),
            (r'union\s+select', 'MODSEC-942100'),
            (r"'\s*or\s*'\d+'", 'MODSEC-942130'),
            (r'\.\./\.\./\.\.[./]', 'MODSEC-930100'),
            (r'/etc/passwd', 'MODSEC-930110'),
            (r'\$\{jndi:', 'MODSEC-944200'),
        ] + _COMMON_RULES
    },
    'haproxy': {
        'name': 'HAProxy WAF',
        'rules': [
            (r'<script', 'HA-XSS-01'),
            (r'javascript:', 'HA-XSS-02'),
            (r'union.*select', 'HA-SQLI-01'),
            (r'\.\.[/\\]', 'HA-LFI-01'),
        ] + _COMMON_RULES
    },
    'azure_frontdoor': {
        'name': 'Azure Front Door WAF',
        'rules': [
            (r'<script[\s>]', 'AZ-XSS-001'),
            (r'on\w+\s*=\s*["\']', 'AZ-XSS-002'),
            (r'union\s+select', 'AZ-SQLI-001'),
            (r'exec\s*\(', 'AZ-RCE-001'),
            (r'/etc/passwd', 'AZ-LFI-001'),
            (r'\$\{jndi:', 'AZ-LOG4J-001'),
        ] + _COMMON_RULES
    },
    'radware': {
        'name': 'Radware AppWall',
        'rules': [
            (r'<script', 'RAD-XSS-001'),
            (r'onerror=', 'RAD-XSS-002'),
            (r'union\s+select', 'RAD-SQLI-001'),
            (r"or\s+1\s*=\s*1", 'RAD-SQLI-002'),
            (r'\.\./\.\./\.\.[./]', 'RAD-LFI-001'),
        ] + _COMMON_RULES
    },
    'fastly': {
        'name': 'Fastly WAF',
        'rules': [
            (r'<script', 'FST-XSS-01'),
            (r'javascript:', 'FST-XSS-02'),
            (r'union.*select', 'FST-SQLI-01'),
            (r'\.\./\.\./\.\.[./]', 'FST-LFI-01'),
            (r'\$\{jndi:', 'FST-LOG4J-01'),
        ] + _COMMON_RULES
    },
    'signal_sciences': {
        'name': 'Signal Sciences WAF',
        'rules': [
            (r'<script[\s>]', 'SS-XSS-01'),
            (r'javascript\s*:', 'SS-XSS-02'),
            (r'union\s+select', 'SS-SQLI-01'),
            (r'sleep\s*\(', 'SS-SQLI-02'),
            (r'/etc/passwd', 'SS-LFI-01'),
            (r'\$\{jndi:', 'SS-LOG4J-01'),
        ] + _COMMON_RULES
    },

    # --- 8 nouveaux WAF ---

    'cloudflare_enterprise': {
        'name': 'Cloudflare Enterprise',
        'rules': [
            (r'<script[\s>]', 'CFE-XSS-001'),
            (r'javascript\s*:', 'CFE-XSS-002'),
            (r'on\w+\s*=', 'CFE-XSS-003'),
            (r'<svg[^>]*on\w+', 'CFE-XSS-004'),
            (r'<img[^>]+onerror', 'CFE-XSS-005'),
            (r'data:text/html', 'CFE-XSS-006'),
            (r'union\s+(all\s+)?select', 'CFE-SQLI-001'),
            (r'or\s+\d+\s*=\s*\d+', 'CFE-SQLI-002'),
            (r'sleep\s*\(', 'CFE-SQLI-003'),
            (r'benchmark\s*\(', 'CFE-SQLI-004'),
            (r'\.[./\\]|%2e%2e', 'CFE-LFI-001'),
            (r'etc/passwd', 'CFE-LFI-002'),
            (r'\$\{jndi:', 'CFE-LOG4J-001'),
            (r'\{\{.*\}\}', 'CFE-SSTI-001'),
            (r';\s*(cat|ls|id|whoami)', 'CFE-RCE-001'),
        ] + _COMMON_RULES
    },

    'modsecurity_paranoia': {
        'name': 'ModSecurity Paranoia Level 4',
        'rules': [
            (r'<script', 'MOD4-XSS-941100'),
            (r'on(error|load|click|focus|blur|mouse\w+)\s*=', 'MOD4-XSS-941110'),
            (r'javascript\s*:', 'MOD4-XSS-941120'),
            (r'vbscript\s*:', 'MOD4-XSS-941130'),
            (r'<svg', 'MOD4-XSS-941140'),
            (r'<img[^>]+on', 'MOD4-XSS-941150'),
            (r'<body[^>]+on', 'MOD4-XSS-941160'),
            (r'eval\s*\(', 'MOD4-XSS-941170'),
            (r'union\s+(all\s+)?select', 'MOD4-SQLI-942100'),
            (r"'\s*(or|and)\s*'", 'MOD4-SQLI-942110'),
            (r'sleep\s*\(', 'MOD4-SQLI-942120'),
            (r'benchmark\s*\(', 'MOD4-SQLI-942130'),
            (r'load_file\s*\(', 'MOD4-SQLI-942140'),
            (r'into\s+(out|dump)file', 'MOD4-SQLI-942150'),
            (r'\.[./\\]|%2e%2e', 'MOD4-LFI-930100'),
            (r'etc/passwd|etc/shadow', 'MOD4-LFI-930110'),
            (r'php://|file://|data://', 'MOD4-LFI-930120'),
            (r'\$\{jndi:', 'MOD4-LOG4J-944200'),
            (r'\{\{.*\}\}', 'MOD4-SSTI-945100'),
            (r';\s*(cat|ls|id|wget|curl)', 'MOD4-RCE-932100'),
            (r'`[^`]+`', 'MOD4-RCE-932110'),
            (r'\$\([^)]+\)', 'MOD4-RCE-932120'),
        ] + _COMMON_RULES
    },

    'wordfence': {
        'name': 'Wordfence (WordPress)',
        'rules': [
            (r'<script[\s>]', 'WF-XSS-001'),
            (r'javascript\s*:', 'WF-XSS-002'),
            (r'on(error|load|click)\s*=', 'WF-XSS-003'),
            (r'alert\s*\(', 'WF-XSS-004'),
            (r'<svg[^>]+on', 'WF-XSS-005'),
            (r'union\s+(all\s+)?select', 'WF-SQLI-001'),
            (r"'\s*or\s*'", 'WF-SQLI-002'),
            (r'drop\s+table', 'WF-SQLI-003'),
            (r'\.[./\\]', 'WF-LFI-001'),
            (r'etc/passwd', 'WF-LFI-002'),
            (r'wp-config\.php', 'WF-LFI-003'),
            (r'\{\{.*\}\}', 'WF-SSTI-001'),
        ] + _COMMON_RULES
    },

    'incapsula': {
        'name': 'Imperva Incapsula Cloud',
        'rules': [
            (r'<script[\s>]', 'INC-XSS-001'),
            (r'javascript\s*:', 'INC-XSS-002'),
            (r'on(error|load|click|focus)\s*=', 'INC-XSS-003'),
            (r'<iframe', 'INC-XSS-004'),
            (r'<object', 'INC-XSS-005'),
            (r'<embed', 'INC-XSS-006'),
            (r'union\s+(all\s+)?select', 'INC-SQLI-001'),
            (r'sleep\s*\(', 'INC-SQLI-002'),
            (r'benchmark\s*\(', 'INC-SQLI-003'),
            (r"or\s+\d+\s*=\s*\d+", 'INC-SQLI-004'),
            (r'\.[./\\]|%2e%2e', 'INC-LFI-001'),
            (r'etc/passwd', 'INC-LFI-002'),
            (r'\$\{jndi:', 'INC-LOG4J-001'),
            (r'\{\{.*\}\}', 'INC-SSTI-001'),
        ] + _COMMON_RULES
    },

    'stackpath': {
        'name': 'StackPath WAF',
        'rules': [
            (r'<script[\s>]', 'SP-XSS-001'),
            (r'javascript\s*:', 'SP-XSS-002'),
            (r'on(error|load|click)\s*=', 'SP-XSS-003'),
            (r'union\s+(all\s+)?select', 'SP-SQLI-001'),
            (r'or\s+\d+\s*=\s*\d+', 'SP-SQLI-002'),
            (r'\.[./\\]|%2e%2e', 'SP-LFI-001'),
            (r'etc/passwd', 'SP-LFI-002'),
            (r'\$\{jndi:', 'SP-LOG4J-001'),
        ] + _COMMON_RULES
    },

    'reblaze': {
        'name': 'Reblaze WAF',
        'rules': [
            (r'<script[\s>]', 'RB-XSS-001'),
            (r'javascript\s*:', 'RB-XSS-002'),
            (r'on(error|load|click|mouse\w+)\s*=', 'RB-XSS-003'),
            (r'<svg[^>]+on', 'RB-XSS-004'),
            (r'data:text/html', 'RB-XSS-005'),
            (r'union\s+(all\s+)?select', 'RB-SQLI-001'),
            (r'sleep\s*\(', 'RB-SQLI-002'),
            (r'benchmark\s*\(', 'RB-SQLI-003'),
            (r"'\s*or\s*'", 'RB-SQLI-004'),
            (r'\.[./\\]|%2e%2e', 'RB-LFI-001'),
            (r'etc/passwd', 'RB-LFI-002'),
            (r'\$\{jndi:', 'RB-LOG4J-001'),
            (r'\{\{.*\}\}', 'RB-SSTI-001'),
            (r';\s*(cat|ls|id)', 'RB-RCE-001'),
        ] + _COMMON_RULES
    },

    'wallarm_enterprise': {
        'name': 'Wallarm Enterprise',
        'rules': [
            (r'<script[\s/>]', 'WLE-XSS-001'),
            (r'javascript:', 'WLE-XSS-002'),
            (r'on(error|load|click|focus|blur|mouse\w+)\s*=', 'WLE-XSS-003'),
            (r'<svg[^>]+on', 'WLE-XSS-004'),
            (r'<img[^>]+onerror', 'WLE-XSS-005'),
            (r'data:text/html', 'WLE-XSS-006'),
            (r'union\s+(all\s+)?select', 'WLE-SQLI-001'),
            (r'sleep\s*\(', 'WLE-SQLI-002'),
            (r'benchmark\s*\(', 'WLE-SQLI-003'),
            (r'load_file\s*\(', 'WLE-SQLI-004'),
            (r'\.[./\\]|%2e%2e', 'WLE-LFI-001'),
            (r'etc/passwd|etc/shadow', 'WLE-LFI-002'),
            (r'php://|file://', 'WLE-LFI-003'),
            (r'\$\{jndi:', 'WLE-LOG4J-001'),
            (r'\{\{.*\}\}', 'WLE-SSTI-001'),
            (r';\s*(cat|ls|id|wget|curl)', 'WLE-RCE-001'),
            (r'`[^`]+`', 'WLE-RCE-002'),
        ] + _COMMON_RULES
    },

    'openappsec': {
        'name': 'open-appsec WAF',
        'rules': [
            (r'<script[\s>]', 'OAS-XSS-001'),
            (r'javascript\s*:', 'OAS-XSS-002'),
            (r'on(error|load|click)\s*=', 'OAS-XSS-003'),
            (r'union\s+(all\s+)?select', 'OAS-SQLI-001'),
            (r'or\s+\d+\s*=\s*\d+', 'OAS-SQLI-002'),
            (r'sleep\s*\(', 'OAS-SQLI-003'),
            (r'\.[./\\]|%2e%2e', 'OAS-LFI-001'),
            (r'etc/passwd', 'OAS-LFI-002'),
            (r'\$\{jndi:', 'OAS-LOG4J-001'),
            (r'\{\{.*\}\}', 'OAS-SSTI-001'),
        ] + _COMMON_RULES
    },
}

CVSS_MAP = {
    'xss': 6.1, 'sqli': 8.8, 'lfi': 7.5, 'ssti': 9.8,
    'rce': 10.0, 'xxe': 8.2, 'ssrf': 8.6, 'mixed': 6.5
}

def check_waf(payload, waf_name):
    profile = WAF_PROFILES.get(waf_name, {})
    forms = normalize_payload(payload)
    for pattern, rule_id in profile.get('rules', []):
        for form in forms:
            try:
                if re.search(pattern, form, re.IGNORECASE | re.DOTALL):
                    return False, rule_id
            except Exception:
                pass
    return True, None

def test_all_wafs(payload):
    results = {}
    passed = []
    for waf_name in WAF_PROFILES:
        ok, rule = check_waf(payload, waf_name)
        results[waf_name] = {'passed': ok, 'blocked_by': rule}
        if ok:
            passed.append(waf_name)
    return results, passed

def score_payload(payload, ptype='unknown'):
    _, passed = test_all_wafs(payload)
    waf_rate = len(passed) / len(WAF_PROFILES) * 100
    cvss = CVSS_MAP.get(ptype, 5.0)
    final = round(waf_rate * 0.7 + cvss * 3, 1)
    return {
        'payload': payload, 'type': ptype,
        'passed_wafs': passed, 'blocked_by_count': len(WAF_PROFILES) - len(passed),
        'waf_bypass_rate': round(waf_rate, 1), 'cvss': cvss,
        'final_score': min(final, 100), 'total_wafs': len(WAF_PROFILES)
    }
