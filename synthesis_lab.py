#!/usr/bin/env python3
"""Local, read-only experiments using the production facts/synthesis pipeline.

Fetch once, then compare models against the same frozen article bodies.
Nothing here invokes harvesting, naming, categorisation, merging or DB writes.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import runpy
import sys
import time

import jsonschema

import ai_pipeline as ai
import perspective_summaries as p
from structured_outputs import check_response_schema
from supabase_client import SupabaseRestClient


PRICE_DATE = '2026-10-23'
PRICE_SOURCE = 'https://developers.openai.com/api/docs/pricing'
# USD per million tokens: ordinary input, cached input, TOTAL output.
# Reasoning tokens are included in output_tokens: never add them a second time.
# Older models: prices verified on their individual official model pages.
PRICES = {
    'gpt-5-nano': (.05, .005, .40),
    'gpt-5-mini': (.25, .025, 2.00),
    'gpt-4o-mini': (.15, .075, .60),
    'gpt-4.1-mini': (.40, .10, 1.60),
    'gpt-5.4-nano': (.20, .02, 1.25),
    'gpt-5.4-mini': (.75, .075, 4.50),
    'gpt-5.4': (2.50, .25, 15.00),
    'gpt-5.5': (5.00, .50, 30.00),
    'gpt-6-luna': (.10, .01, .50),
    'gpt-6.1-sol': (2.00, .10, 10.00),
    'gpt-6-astra': (10.00, 1.00, 50.00),
}
STAGES = {'perspective_facts': 'extraction',
          'perspective_novelty_audit': 'audit', 'perspective_summary': 'writing'}
DEFAULT_STAGES = {name: {'model': 'gpt-6-luna', 'reasoning_effort': effort}
                  for name, effort in [('extraction', 'low'), ('audit', 'low'), ('writing', 'medium')]}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def safe_error(exc):
    text = f'{type(exc).__name__}: {exc}'
    for name in ('OPENAI_API_KEY', 'SUPABASE_SECRET_KEY'):
        secret = os.environ.get(name)
        if secret:
            text = text.replace(secret, '[klucz usunięty]')
    return re.sub(r'\bsk-[\w-]+', '[klucz usunięty]', text)[:1200]


class ReadOnlySupabase(SupabaseRestClient):
    def request(self, method, path, **kwargs):
        if method.upper() != 'GET':
            raise RuntimeError('Laboratorium dopuszcza wyłącznie odczyt GET z bazy.')
        return super().request(method, path, **kwargs)


def find_topics(client, selector, limit=30):
    if not isinstance(selector, str) or not selector.strip():
        raise ValueError('Wpisz tytuł lub topic_id w TOPICS.')
    selector = selector.strip()
    columns = 'topic_id,headline_pl,status,merged_into_topic_id,last_seen_at'
    rows = client.select('topics', columns=columns, filters=[('topic_id', 'eq.' + selector)], limit=2)
    if rows:
        return rows
    # Escape LIKE wildcards. The client URL-encodes these values separately.
    escaped = selector.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_').replace('*', '\\*')
    return client.select('topics', columns=columns,
                         filters=[('headline_pl', 'ilike.%' + escaped + '%'),
                                  ('merged_into_topic_id', 'is.null')],
                         order='last_seen_at.desc,topic_id.asc', limit=limit)


def resolve_topic(client, selector):
    rows = find_topics(client, selector)
    exact = [row for row in rows if row['headline_pl'].casefold() == selector.strip().casefold()]
    if exact:
        rows = exact
    if len(rows) != 1:
        choices = '\n'.join(f"  {r['topic_id']} — {r['headline_pl']}" for r in rows)
        raise ValueError(f'Wybór „{selector}”: znaleziono {len(rows)} wątków. '
                         f'Podaj dokładny topic_id.\n{choices}')
    if rows[0].get('merged_into_topic_id'):
        raise ValueError('Ten wątek został scalony. Użyj topic_id: ' + rows[0]['merged_into_topic_id'])
    return rows[0]


def fetch_snapshot(client, selectors):
    if not selectors:
        raise ValueError('Lista TOPICS jest pusta.')
    topics = [resolve_topic(client, selector) for selector in selectors]
    records, seen = [], set()
    for topic in topics:
        tid = topic['topic_id']
        if tid in seen:
            continue
        seen.add(tid)
        links = client.select_all('topic_articles', columns='article_id,assigned_at',
                                  filters=[('topic_id', 'eq.' + tid)])
        ids = sorted({link['article_id'] for link in links})
        rows = []
        for start in range(0, len(ids), 100):
            values = ','.join(json.dumps(aid) for aid in ids[start:start + 100])
            rows.extend(client.select_all('articles', filters=[('article_id', f'in.({values})')]))
        by_id = {row['article_id']: row for row in rows}
        missing = [aid for aid in ids if aid not in by_id or not str(by_id[aid].get('body') or '').strip()]
        if not ids or missing:
            raise ValueError(f"{topic['headline_pl']}: brak artykułów lub pełnych treści: {missing[:10]}")
        articles = [ai.article_for_ai(by_id[aid]) for aid in ids]
        articles.sort(key=lambda a: (a.get('published_at') or '', a['article_id']))
        records.append({'topic': topic, 'articles': articles})
        print(f"Pobrano: {topic['headline_pl']} — {len(articles)} pełnych artykułów.", flush=True)
    return {'schema_version': 1, 'fetched_at': datetime.now(timezone.utc).isoformat(), 'topics': records}


def validate_snapshot(snapshot):
    if snapshot.get('schema_version') != 1 or not snapshot.get('topics'):
        raise ValueError('Niepoprawny snapshot wejściowy.')
    topic_ids = set()
    for record in snapshot['topics']:
        tid = record['topic']['topic_id']
        if tid in topic_ids:
            raise ValueError('Powtórzony topic_id w wejściu.')
        topic_ids.add(tid)
        ids = [a['article_id'] for a in record['articles']]
        if not ids or len(ids) != len(set(ids)) or any(not str(a.get('body_original') or '').strip() for a in record['articles']):
            raise ValueError('Artykuły muszą mieć unikalne ID i pełne treści.')


def settings_for(variant, stage, config):
    settings = {**DEFAULT_STAGES[stage], **variant.get('stages', {}).get(stage, {})}
    model = settings['model']
    if not isinstance(model, str) or not model.strip():
        raise ValueError('Model musi mieć niepustą nazwę.')
    effort = settings.get('reasoning_effort')
    if model.startswith(('gpt-4', 'chatgpt-4')):
        effort = None
    elif effort not in (None, 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'):
        raise ValueError('Nieznany reasoning_effort: ' + str(effort))
    if model.startswith(('gpt-6.1-sol', 'gpt-6-astra')) and effort in ('none', 'minimal'):
        raise ValueError(model + ' nie obsługuje none/minimal; użyj low lub medium.')
    if re.sub(r'-\d{4}-\d{2}-\d{2}$', '', model) in ('gpt-5-nano', 'gpt-5-mini') and effort in ('none', 'xhigh', 'max'):
        raise ValueError(model + ' obsługuje minimal/low/medium/high.')
    if model.startswith(('gpt-5.4', 'gpt-5.5')) and effort in ('minimal', 'max'):
        raise ValueError(model + ' obsługuje none/low/medium/high/xhigh.')
    if model.startswith('gpt-6') and effort == 'minimal':
        raise ValueError(model + ' nie obsługuje minimal; użyj low.')
    return {'model': model, 'reasoning_effort': effort,
            'max_output_tokens': settings.get('max_output_tokens', config.get('MAX_OUTPUT_TOKENS', 16000)),
            'timeout_seconds': settings.get('timeout_seconds', config.get('TIMEOUT_SECONDS', 300))}


def validate_variants(config):
    variants = config.get('VARIANTS') or []
    seen = set()
    if not variants:
        raise ValueError('Lista VARIANTS jest pusta.')
    for variant in variants:
        name = variant.get('name')
        if not isinstance(name, str) or not name.strip() or name in seen:
            raise ValueError('Nazwy wariantów muszą być niepuste i unikalne.')
        mode = variant.get('mode', 'full')
        if mode not in ('full', 'writing'):
            raise ValueError('mode musi być full lub writing.')
        if mode == 'writing' and variant.get('facts_from') not in seen:
            raise ValueError('facts_from musi wskazywać wcześniejszy wariant z tej listy.')
        if set(variant.get('stages', {})) - set(DEFAULT_STAGES):
            raise ValueError('Dozwolone etapy: extraction, audit, writing.')
        for stage in DEFAULT_STAGES:
            settings = settings_for(variant, stage, config)
            if not isinstance(settings['model'], str) or not settings['model'].strip():
                raise ValueError('Model musi mieć niepustą nazwę.')
            if settings['max_output_tokens'] < 1 or settings['timeout_seconds'] <= 0:
                raise ValueError('Limity muszą być dodatnie.')
        seen.add(name)
    if config.get('MAX_CALLS_PER_TOPIC', 16) < 3:
        raise ValueError('MAX_CALLS_PER_TOPIC musi wynosić co najmniej 3.')


def usage_of(response):
    usage = getattr(response, 'usage', None)
    details = getattr(usage, 'input_tokens_details', None)
    output_details = getattr(usage, 'output_tokens_details', None)
    return {'input': int(getattr(usage, 'input_tokens', 0) or 0),
            'cached_input': int(getattr(details, 'cached_tokens', 0) or 0),
            'output': int(getattr(usage, 'output_tokens', 0) or 0),
            'reasoning': int(getattr(output_details, 'reasoning_tokens', 0) or 0),
            'available': usage is not None}


def cost_of(model, usage, prices):
    # Only exact aliases or dated snapshots; never silently price an unknown model.
    key = model if model in prices else re.sub(r'-\d{4}-\d{2}-\d{2}$', '', model)
    if key not in prices or not usage.get('available', True):
        return None
    inp, cached, out = prices[key]
    n_cached = min(usage.get('cached_input', 0), usage['input'])
    return ((usage['input'] - n_cached) * inp + n_cached * cached + usage['output'] * out) / 1_000_000


class StageRunner:
    def __init__(self, variant, config, directory, client_factory=None):
        self.variant, self.config, self.directory = variant, config, Path(directory)
        self.client_factory = client_factory
        self.calls, self.skipped = [], []
        self.prices = {**PRICES, **config.get('PRICE_OVERRIDES', {})}

    def __call__(self, instructions, data, schema, name):
        if name not in STAGES:
            raise RuntimeError('Nieoczekiwany etap (laboratorium nie wykonuje napraw): ' + name)
        stage = STAGES[name]
        reserve = 2 if stage == 'extraction' else 1 if stage == 'audit' else 0
        if len(self.calls) >= self.config.get('MAX_CALLS_PER_TOPIC', 16) - reserve:
            self.skipped.append(name)
            return {}
        settings = settings_for(self.variant, stage, self.config)
        schema = copy.deepcopy(schema)
        if stage == 'extraction':
            # Existing title is input; categories are outside this experiment.
            for field in ('headline_pl', 'categories'):
                schema['properties'].pop(field, None)
                if field in schema['required']:
                    schema['required'].remove(field)
            instructions += '\nNie twórz tytułu ani kategorii; zwróć wyłącznie article_results.'
        check_response_schema(schema)
        request = {'model': settings['model'], 'instructions': instructions + '\n' + ai.POLISH_TITLE_INSTRUCTIONS,
                   'input': json.dumps(data, ensure_ascii=False)
                   + '\n\nReturn only valid JSON. Do not add any commentary outside the JSON object.',
                   'text': {'format': {'type': 'json_schema', 'name': name, 'strict': True, 'schema': schema}},
                   'max_output_tokens': settings['max_output_tokens'], 'store': False,
                   'service_tier': 'default'}
        if settings['reasoning_effort'] is not None:
            request['reasoning'] = {'effort': settings['reasoning_effort']}
        entry = {'stage': stage, 'schema_name': name, 'settings': settings, 'status': 'started',
                 'input_article_ids': [a['article_id'] for a in data.get('all_articles', [])]}
        self.calls.append(entry)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f'call-{len(self.calls):02d}-{stage}.json'
        save_json(path, {'request': request, 'result': entry})
        print(f"  {self.variant['name']}: {stage}, model {settings['model']}, zapytanie {len(self.calls)}", flush=True)
        started = time.monotonic()
        raw = ''
        try:
            factory = self.client_factory
            if factory is None:
                from openai import OpenAI
                factory = OpenAI
            with factory(api_key=ai.openai_api_key(), timeout=settings['timeout_seconds'], max_retries=0) as client:
                response = client.responses.create(**request)
            entry['usage'] = usage_of(response)
            entry['response_model'] = getattr(response, 'model', None)
            entry['response_id'] = getattr(response, 'id', None)
            entry['cost_usd'] = cost_of(settings['model'], entry['usage'], self.prices)
            raw = response.output_text or ''
            parsed = {}
            if getattr(response, 'status', None) != 'completed':
                entry.update(status='omitted', error='Odpowiedź niekompletna; bez ponowienia.')
            else:
                try:
                    parsed = ai.extract_json(raw)
                    jsonschema.Draft202012Validator(schema).validate(parsed)
                    entry['status'] = 'accepted'
                except (ValueError, jsonschema.ValidationError) as exc:
                    # Same omission policy as production: independently usable
                    # extraction/writing items may survive; no second request.
                    entry.update(status='partial', error=safe_error(exc))
                    if stage == 'audit' or not isinstance(parsed, dict):
                        parsed = {}
            return parsed
        except Exception as exc:
            entry.update(status='error', error=safe_error(exc), cost_usd=None)
            raise
        finally:
            entry['seconds'] = round(time.monotonic() - started, 3)
            save_json(path, {'request': request, 'raw_output': raw, 'result': entry})


def run_topic(record, variant, config, directory, parent=None, client_factory=None):
    topic, articles = record['topic'], copy.deepcopy(record['articles'])
    payload = {'topic': {'topic_id': topic['topic_id'], 'working_title_pl': topic['headline_pl']},
               'all_articles': articles, 'new_article_ids': [a['article_id'] for a in articles],
               'extraction_model': settings_for(variant, 'extraction', config)['model']}
    runner = StageRunner(variant, config, directory, client_factory)
    started = time.monotonic()
    result = {'topic': topic, 'variant': variant, 'status': 'started', 'calls': runner.calls}
    try:
        if variant.get('mode') == 'writing':
            if not parent or parent.get('status') != 'completed':
                raise ValueError('Brak poprawnego wyniku facts_from dla tego wątku.')
            base = copy.deepcopy(parent['result'])
            payload['new_article_ids'] = []
            payload['previous_aggregation'] = {'base_summary': base, 'current_summary': base,
                'perspective_state': base['perspective_state'], 'needs_narrative_refresh': True,
                'processed_article_ids': [a['article_id'] for a in articles]}
        result['result'] = p.generate(payload, runner, ai.normalize_generated_text,
                                      max_payload_chars=config.get('MAX_PAYLOAD_CHARS', 300000),
                                      allow_omissions=True)
        result['status'] = 'completed'
    except Exception as exc:
        result.update(status='error', error=safe_error(exc))
    result.update(seconds=round(time.monotonic() - started, 3), skipped_stages=runner.skipped)
    costs = [call.get('cost_usd') for call in runner.calls]
    result['known_cost_usd'] = sum(value for value in costs if value is not None)
    result['cost_complete'] = all(value is not None for value in costs)
    result['tokens'] = {key: sum(call.get('usage', {}).get(key, 0) for call in runner.calls)
                        for key in ('input', 'cached_input', 'output', 'reasoning')}
    return result


def code_fingerprint():
    # Include validation/normalisation, not just prompts. Older results remain
    # viewable but must not be reused after the experiment's code changes.
    names = ('synthesis_lab.py', 'ai_pipeline.py', 'perspective_summaries.py',
             'editorial_integrity.py', 'structured_outputs.py', 'source_tester.py')
    return digest({name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in names})


def run_experiments(snapshot, config, root, client_factory=None, repeat=False):
    validate_snapshot(snapshot)
    validate_variants(config)
    root = Path(root)
    rows, known = [], {}
    repeat_key = datetime.now(timezone.utc).isoformat() if repeat else None
    for record in snapshot['topics']:
        for variant in config['VARIANTS']:
            parent = known.get((record['topic']['topic_id'], variant.get('facts_from')))
            key = digest({'input': record, 'variant': variant, 'code': code_fingerprint(),
                          'config': {key: config[key] for key in ('MAX_CALLS_PER_TOPIC', 'MAX_OUTPUT_TOKENS',
                                     'MAX_PAYLOAD_CHARS', 'TIMEOUT_SECONDS', 'PRICE_OVERRIDES') if key in config},
                          'parent': parent.get('job_id') if parent else None, 'repeat': repeat_key})[:24]
            directory = root / key
            result_path = directory / 'result.json'
            if result_path.exists():
                row = json.loads(result_path.read_text(encoding='utf-8'))
                print(f"Zapisany wynik: {variant['name']} / {record['topic']['headline_pl']} (bez API).", flush=True)
            elif directory.exists():
                raise ValueError(f'Przerwana próba w {directory}. Zachowano ślady zapytań. '
                                 'Sprawdź je; --repeat uruchomi jawnie nową płatną próbę.')
            else:
                directory.mkdir(parents=True)
                row = run_topic(record, variant, config, directory, parent, client_factory)
                row.update(job_id=key, prompt_version=ai.PROMPT_VERSION, input_hash=digest(record),
                           price_date=PRICE_DATE, price_source=PRICE_SOURCE)
                save_json(result_path, row)
            known[(record['topic']['topic_id'], variant['name'])] = row
            rows.append(row)
            write_report(rows, root.parent / 'report.html', snapshot['topics'])
    return rows


def write_report(rows, path, records=()):
    esc = lambda value: html.escape(str(value), quote=True)
    sections = []
    for tid in dict.fromkeys(row['topic']['topic_id'] for row in rows):
        selected = [row for row in rows if row['topic']['topic_id'] == tid]
        cards = []
        for row in selected:
            result = row.get('result') or {}
            variant = row['variant']
            settings = ' · '.join(f"{stage}: {settings_for(variant, stage, {})['model']}"
                                  for stage in (('writing',) if variant.get('mode') == 'writing' else DEFAULT_STAGES))
            tokens = row['tokens']
            charge = f"${row['known_cost_usd']:.6f}" + ('' if row['cost_complete'] else ' + koszt nieznany')
            metadata = f"{row['status']} · {row['seconds']:.1f} s · {len(row['calls'])} zapytań · {charge}"
            body = ''.join('<p>' + esc(text) + '</p>' for text in result.get('summary_pl', '').split('\n\n') if text.strip())
            if not body:
                body = '<p class="notice">' + esc(row.get('error') or 'Brak syntezy po walidacji; sprawdź fakty i diagnostykę.') + '</p>'
            perspectives = result.get('perspective_sections') or {}
            for lane, label in [('LEFT', 'Ustalenia źródeł lewicowych'), ('CENTER', 'Ustalenia źródeł centrowych'),
                                ('RIGHT', 'Ustalenia źródeł prawicowych'), ('EDITORIAL', 'Oceny i interpretacje'),
                                ('STATE', 'Ustalenia źródeł państwowych')]:
                if perspectives.get(lane):
                    body += '<h4>' + label + '</h4>' + ''.join('<p>' + esc(f['text_pl']) + '</p>' for f in perspectives[lane])
            facts = result.get('perspective_facts') or []
            details = '<ol>' + ''.join('<li>' + esc(f['text_pl']) + '<small>' + esc(
                f"{f.get('kind')} · {f.get('lane')} · artykuły: {', '.join(f['article_ids'])}") + '</small></li>' for f in facts) + '</ol>'
            quality = json.dumps(result.get('quality_report') or {}, ensure_ascii=False, indent=2)
            calls = ''.join('<li>' + esc(f"{c['stage']} · {c['settings']['model']} · {c['status']} · {c.get('seconds', 0)} s") + '</li>' for c in row['calls'])
            shared = '<p class="notice">Te same fakty z wariantu ' + esc(variant['facts_from']) + '; koszt tutaj obejmuje samo pisanie.</p>' if variant.get('mode') == 'writing' else ''
            cards.append('<article><h3>' + esc(variant['name']) + '</h3><small>' + esc(settings)
                         + '</small><p class="meta">' + esc(metadata) + '</p><small>'
                         + esc(f"Tokeny: wejście {tokens['input']} (cache {tokens['cached_input']}), wyjście {tokens['output']} (w tym rozumowanie {tokens['reasoning']})")
                         + '</small>' + shared + body + '<details><summary>Wszystkie fakty (' + str(len(facts))
                         + ')</summary>' + details + '</details><details><summary>Zapytania i diagnostyka</summary><ol>'
                         + calls + '</ol><pre>' + esc(quality) + '</pre></details></article>')
        articles = next((r['articles'] for r in records if r['topic']['topic_id'] == tid), [])
        source_rows = []
        for article in articles:
            label = esc(f"{article.get('source_name')} · {article.get('source_profile')} · {article.get('published_at')} — {article.get('title_original')}")
            url = str(article.get('canonical_url') or '')
            if url.startswith(('https://', 'http://')):
                label = '<a href="' + esc(url) + '">' + label + '</a>'
            source_rows.append('<li>' + label + '<small>' + esc(article['article_id']) + '</small></li>')
        sources = '<details><summary>Materiały wejściowe (' + str(len(articles)) + ')</summary><ol>' + ''.join(source_rows) + '</ol></details>'
        sections.append('<section><h2>' + esc(selected[0]['topic']['headline_pl']) + '</h2>' + sources + '<div class="grid">' + ''.join(cards) + '</div></section>')
    total = sum(row['known_cost_usd'] for row in rows)
    document = '<!doctype html><html lang="pl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Porównanie syntez</title><style>body{font:16px/1.6 system-ui;margin:24px;background:#f6f1e9;color:#24211e}h1,h2,h3{line-height:1.2}.grid{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(330px,1fr);gap:20px;overflow-x:auto;align-items:start;padding-bottom:15px}article{background:white;padding:24px;border:1px solid #ddd}small{display:block;color:#665f56;font-size:12px}details{margin-top:20px}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px}li{margin-bottom:12px}.meta,.notice{background:#f2eee6;padding:12px}section{margin:40px 0}p{overflow-wrap:anywhere}</style><h1>Porównanie syntez</h1><p>Zamrożone artykuły, obecne prompty i walidacje. Wyniki zapisane lokalnie. Koszt przybliżony według cennika z ' + PRICE_DATE + ', Standard, bez dopłat za region, długi kontekst i zapis cache. Rozumowanie mieści się w tokenach wyjścia.</p><p>Łączny znany koszt prób w tym porównaniu: $' + f'{total:.6f}' + ' (także wcześniejszych wyników użytych bez ponownego API).</p>' + ''.join(sections) + '</html>'
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(document, encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('synthesis_lab_config.py'))
    parser.add_argument('--env-file', type=Path, default=Path('.env.lab'))
    parser.add_argument('--search', help='Szukaj tytułu/ID w bazie; bez AI.')
    parser.add_argument('--fetch', action='store_true', help='Pobierz nowy snapshot; bez AI, chyba że dodasz --run.')
    parser.add_argument('--run', action='store_true', help='Wykonaj płatne zapytania modeli na zapisanym snapshocie.')
    parser.add_argument('--repeat', action='store_true', help='Z --run: jawnie powtórz próby zamiast używać lokalnych wyników.')
    parser.add_argument('--list-models', action='store_true', help='Pokaż modele widoczne dla OPENAI_API_KEY, bez generowania.')
    args = parser.parse_args(argv)
    if args.env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=False)
    if args.list_models:
        from openai import OpenAI
        with OpenAI(api_key=ai.openai_api_key(), max_retries=0) as client:
            print('\n'.join(sorted(model.id for model in client.models.list() if model.id.startswith(('gpt-', 'o3', 'o4')))))
        return 0
    if args.search:
        rows = find_topics(ReadOnlySupabase(), args.search)
        for row in rows:
            print(f"{row['topic_id']} — {row['headline_pl']}")
        return 0
    if not args.config.exists():
        raise ValueError('Skopiuj synthesis_lab_config.example.py do synthesis_lab_config.py i wpisz TOPICS.')
    config = runpy.run_path(str(args.config))
    validate_variants(config)
    snapshot_path = Path(config.get('SNAPSHOT_PATH', 'lab-data/input.json'))
    if args.fetch:
        snapshot = fetch_snapshot(ReadOnlySupabase(), config.get('TOPICS', []))
        validate_snapshot(snapshot)
        save_json(snapshot_path, snapshot)
        print('Zapisano snapshot: ' + str(snapshot_path.resolve()))
    if not snapshot_path.exists():
        if args.fetch:
            return 0
        raise ValueError('Najpierw uruchom z --fetch, aby pobrać artykuły do lokalnego pliku.')
    snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
    validate_snapshot(snapshot)
    print(f"Plan: {len(snapshot['topics'])} wątków × {len(config['VARIANTS'])} wariantów; "
          f"maksymalnie {config.get('MAX_CALLS_PER_TOPIC', 16)} zapytań na wątek i wariant. "
          'Modele są wywoływane tylko z --run.')
    for variant in config['VARIANTS']:
        active = ['writing'] if variant.get('mode') == 'writing' else list(DEFAULT_STAGES)
        print(variant['name'] + ': ' + ', '.join(stage + '=' + settings_for(variant, stage, config)['model'] for stage in active))
    if not args.run:
        return 0
    ai.openai_api_key()
    root = Path(config.get('RESULTS_DIR', 'lab-data/results'))
    rows = run_experiments(snapshot, config, root, repeat=args.repeat)
    print('Raport: ' + str((root.parent / 'report.html').resolve()))
    return 1 if any(row['status'] != 'completed' for row in rows) else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print('Błąd: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
