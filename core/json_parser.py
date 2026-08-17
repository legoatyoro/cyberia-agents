import json
import re

def safe_json_parse(content, default=None):
    if default is None:
        default = {}
    if not content:
        return default

    # Pass 1 - direct parse
    try:
        return json.loads(content)
    except Exception:
        pass

    # Pass 2 - strip backticks UNIQUEMENT puis parse
    cleaned = re.sub(r'```(?:json)?', '', content).strip('`').strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Pass 2.3 - array JSON avec prefixe texte (ex: "Here are the payloads: [...]")
    bracket_start = cleaned.find('[')
    brace_start_check = cleaned.find('{')
    if bracket_start >= 0 and (brace_start_check < 0 or bracket_start < brace_start_check):
        from_bracket = cleaned[bracket_start:]
        try:
            parsed_array = json.loads(from_bracket)
            if isinstance(parsed_array, list):
                return {'mutations': parsed_array}
        except Exception:
            pass

    # Pass 2.5 - prefixe texte avant le JSON (ex: "Here are the mutations: {...")
    brace_start = cleaned.find('{')
    if brace_start > 0:
        from_brace = cleaned[brace_start:]
        try:
            return json.loads(from_brace)
        except Exception:
            pass

    # Pass 3 - extraire bloc {...} depuis cleaned
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass

    # Pass 4 - flatten puis extraire
    oneline = re.sub(r'\s+', ' ', cleaned)
    match2 = re.search(r'\{.*\}', oneline, re.DOTALL)
    if match2:
        try:
            return json.loads(match2.group())
        except Exception:
            pass

    # Pass 5 - nettoyage agressif puis retry
    aggressive = content
    aggressive = re.sub(r'```(?:json)?', '', aggressive)
    aggressive = aggressive.replace('\\"', '"')
    aggressive = aggressive.replace('\\n', ' ')
    aggressive = aggressive.replace('\\t', ' ')
    aggressive = aggressive.replace('\\r', '')
    aggressive = re.sub(r'\\(?!["\\/bfnrtu])', '', aggressive)
    match3 = re.search(r'\{.*\}', aggressive, re.DOTALL)
    if match3:
        try:
            return json.loads(match3.group())
        except Exception:
            pass

    return {**default, 'summary': content[:300], 'raw': True}
