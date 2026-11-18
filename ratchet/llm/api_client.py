"""OpenAI API JSON request transport with usage metadata."""
import datetime
import json
import os
import time
import urllib.error
import urllib.request
import jsonschema
from pathlib import Path


def request_body(prompt, schema, temperature=None, max_tokens=None):
    """Build the request body from the model, prompt and response schema."""
    body = {'model': os.environ['RATCHET_MODEL'], 'messages': [{'role': 'user', 'content': prompt}],
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'response', 'strict': True, 'schema': schema}}}
    if temperature is not None:
        body['temperature'] = temperature
    if max_tokens is not None:
        body['max_tokens'] = max_tokens
    return body


def call(request, schema, run_dir, call_id, purpose, temperature=None, max_tokens=None, timeout=600, retries=2, dry_run=False):
    """Send one request and return response metadata for the accounting layer."""
    body = request_body(request, schema, temperature, max_tokens)
    url = os.environ['RATCHET_API_BASE'].rstrip('/') + '/chat/completions'
    key = os.environ['RATCHET_API_KEY']
    root = Path(run_dir) / 'calls' / call_id
    root.mkdir(parents=True, exist_ok=False)
    (root / 'request.json').write_text(json.dumps(body, indent=2) + '\n')
    started_at = time.monotonic()
    start_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    response = None
    error = None
    attempts = 0
    if dry_run:
        from ratchet.core import count
        text = json.dumps({'rationale': 'Synthetic response', 'asm': 'addi x5, x5, 1\n' * 40})
        response = {'model': body['model'], 'choices': [{'message': {'content': text}}],
                    'usage': {'prompt_tokens': count(request), 'completion_tokens': count(text)}}
    for attempts in range(0 if dry_run else retries + 1):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=timeout) as stream:
                response = json.load(stream)
            break
        except (urllib.error.URLError, TimeoutError) as exc:
            error = str(exc)
            if attempts == retries:
                break
            time.sleep(min(2 ** attempts, 30))
    usage = (response or {}).get('usage') or {}
    details = usage.get('prompt_tokens_details') or {}
    completion = usage.get('completion_tokens_details') or {}
    usage_raw = [{'input_tokens': usage.get('prompt_tokens'), 'output_tokens': usage.get('completion_tokens'),
                  'cached_input_tokens': details.get('cached_tokens', 0), 'reasoning_output_tokens': completion.get('reasoning_tokens', 0)}] if usage.get('prompt_tokens') is not None and usage.get('completion_tokens') is not None else []
    text = ''
    valid = False
    if response:
        try:
            text = response['choices'][0]['message']['content']
            parsed = json.loads(text)
            jsonschema.validate(parsed, schema)
            valid = True
        except (KeyError, IndexError, TypeError, ValueError, jsonschema.ValidationError):
            pass
    if text:
        (root / 'last_message.json').write_text(text)
    meta = {'call_id': call_id, 'purpose': purpose, 'started': True, 'start_utc': start_utc,
            'end_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'elapsed_s': time.monotonic() - started_at,
            'usage_raw': usage_raw, 'usage_known': bool(usage_raw), 'contaminated': False, 'n_reconnect': attempts,
            'transport_failure': response is None, 'rate_limit_evidence': [], 'schema_ok': valid,
            'ok': response is not None and valid and bool(usage_raw), 'exit_code': 0 if response else 1,
            'model_reported': (response or {}).get('model'), 'effort_reported': None, 'cli_version': None,
            'quota_or_rate_limit': False, 'error': error, 'simulated': dry_run}
    (root / 'meta.json').write_text(json.dumps(meta, indent=2) + '\n')
    return meta
