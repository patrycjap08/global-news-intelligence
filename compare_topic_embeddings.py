#!/usr/bin/env python3
"""Read-only A/B embedding comparison. No harvesting, summaries or DB writes."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

import ai_pipeline as ai
from supabase_client import SupabaseRestClient


DEFAULT_TOPIC_IDS = (
    'topic_perspectives_d47c451ef7a0c2a4a8327596',
    'topic_perspectives_e76e6853f89111c7a22d8d61',
    'topic_perspectives_449f14cebf8083ee911b91dc',
    'topic_perspectives_f63c6bcbe03aa9b33e8b63d9',
    'topic_perspectives_802d78b36ab2940d59552746',
    'topic_perspectives_bfe87060175e86a633d35bee',
    'topic_perspectives_5897d4f7a483837ce7c52e4f',
    'topic_perspectives_0bb17b14683705e57fd24b02',
)
VARIANTS = ('current', 'title_description')
SUMMARY_COLUMNS = (
    'topic_id,version,updated_at,base_topic:summary->base_summary->topic,'
    'base_text:summary->base_summary->summary_pl,legacy_topic:summary->topic,'
    'legacy_text:summary->summary_pl,base_format:summary->base_summary->perspective_version,'
    'legacy_format:summary->perspective_version'
)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def parse_topic_ids(value):
    ids = list(dict.fromkeys(re.split(r'[\s,]+', value.strip()))) if value.strip() else list(DEFAULT_TOPIC_IDS)
    if not 2 <= len(ids) <= 20 or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', tid) for tid in ids):
        raise ValueError('Podaj od 2 do 20 poprawnych topic_id oddzielonych przecinkami lub spacjami.')
    return ids


def select_ids(client, table, column, ids, columns, order):
    rows = []
    for start in range(0, len(ids), 80):
        offset = 0
        while True:
            page = client.select(table, columns=columns,
                filters=[(column, 'in.(' + ','.join(ids[start:start + 80]) + ')')],
                order=order, limit=500, offset=offset)
            rows.extend(page)
            if len(page) < 500:
                break
            offset += len(page)
    return rows


def load_topics(client, ids):
    topics = {row['topic_id']: row for row in select_ids(client, 'topics', 'topic_id', ids,
        'topic_id,headline_pl,status,merged_into_topic_id,updated_at', 'topic_id.asc')}
    summaries = {row['topic_id']: row for row in select_ids(client, 'topic_summaries', 'topic_id', ids,
        SUMMARY_COLUMNS, 'topic_id.asc')}
    links = select_ids(client, 'topic_articles', 'topic_id', ids,
                       'topic_id,article_id', 'topic_id.asc,article_id.asc')
    article_ids = sorted({row['article_id'] for row in links})
    # Fetch only headlines/dates. Body/original text is never downloaded.
    articles = {row['article_id']: row for row in select_ids(client, 'articles', 'article_id', article_ids,
        'article_id,title,published_at,fetched_at', 'article_id.asc')}
    prepared = []
    for tid in ids:
        if tid not in topics:
            raise ValueError(f'Nie znaleziono wątku {tid}.')
        row, summary = topics[tid], summaries.get(tid, {})
        base = summary.get('base_topic')
        if not isinstance(base, dict):
            base = summary.get('legacy_topic') or {}
        description = str(base.get('what_happened_one_sentence_pl') or '').strip()
        if not description:
            raise ValueError(f'Wątek {tid} nie ma zapisanego krótkiego opisu. Nie zastępuję go syntezą ani opisem AI.')
        linked = [link['article_id'] for link in links if link['topic_id'] == tid]
        if any(aid not in articles for aid in linked):
            raise ValueError(f'Brakuje metadanych artykułów wątku {tid}; porównanie byłoby niepełne.')
        recent = sorted((articles[aid] for aid in linked), key=lambda a: (
            str(a.get('published_at') or a.get('fetched_at') or ''), str(a['article_id'])), reverse=True)
        summary_text = summary.get('base_text')
        if summary_text is None:
            summary_text = summary.get('legacy_text')
        prepared.append({
            **row, 'what_happened_one_sentence_pl': description,
            'summary_pl': str(summary_text or '').strip()[:ai.TOPIC_MERGE_SUMMARY_CHAR_LIMIT],
            'recent_article_titles': [str(a.get('title') or '')[:300] for a in recent[:5]
                                      if str(a.get('title') or '').strip()],
            'summary_version': summary.get('version'), 'summary_updated_at': summary.get('updated_at'),
            'generation': ai.topic_generation(tid, {'perspective_version':
                summary.get('base_format') or summary.get('legacy_format')}),
        })
    return prepared


def prepare_inputs(topics):
    records, texts, positions = [], [], {}
    for variant in VARIANTS:
        for topic in topics:
            if variant == 'current':
                text = ai._topic_embedding_text(topic)
            else:
                text = ('Tytuł wątku: ' + str(topic['headline_pl']).strip()
                        + '\nOpis: ' + topic['what_happened_one_sentence_pl'])
            if text not in positions:
                positions[text] = len(texts)
                texts.append(text)
            records.append({'topic_id': topic['topic_id'], 'variant': variant, 'text': text,
                            'sha256': hashlib.sha256(text.encode()).hexdigest(),
                            'embedding_index': positions[text]})
    return records, texts


def request_vectors(client, texts):
    for attempt in range(ai.TOPIC_MERGE_EMBEDDING_MAX_RETRIES):
        try:
            response = client.embeddings.create(input=texts, model=ai.TOPIC_MERGE_EMBEDDING_MODEL,
                                                dimensions=ai.TOPIC_MERGE_EMBEDDING_DIMENSIONS)
            break
        except Exception as exc:
            if not ai.is_retryable_openai_error(exc) or attempt + 1 >= ai.TOPIC_MERGE_EMBEDDING_MAX_RETRIES:
                raise
            ai.wait_before_openai_retry(attempt, exc, retry_limit=ai.TOPIC_MERGE_EMBEDDING_MAX_RETRIES)
    data = sorted(response.data, key=lambda item: item.index)
    if [item.index for item in data] != list(range(len(texts))):
        raise ValueError('API nie zwróciło dokładnie jednego wektora dla każdego tekstu.')
    vectors = [[float(v) for v in item.embedding] for item in data]
    if any(len(v) != ai.TOPIC_MERGE_EMBEDDING_DIMENSIONS or not all(math.isfinite(x) for x in v)
           or not any(v) for v in vectors):
        raise ValueError('API zwróciło niepoprawne wektory; raport nie zostanie policzony.')
    usage = getattr(response, 'usage', None)
    return vectors, {key: getattr(usage, key, None) for key in ('prompt_tokens', 'total_tokens')}


def build_report(topics, inputs, vectors, usage, started_at):
    ids = [t['topic_id'] for t in topics]
    ukraine_ids = ai.ukraine_topic_ids(topics)
    by_id = {t['topic_id']: t for t in topics}
    refs = {(row['variant'], row['topic_id']): row['embedding_index'] for row in inputs}
    pairs = []
    for i, left in enumerate(ids):
        for right in ids[i + 1:]:
            scores = {variant: ai._cosine_similarity(vectors[refs[variant, left]], vectors[refs[variant, right]])
                      for variant in VARIANTS}
            threshold = ai.embedding_pair_threshold(left, right, ai.TOPIC_MERGE_EMBEDDING_MIN_SIMILARITY, ukraine_ids)
            pairs.append({'topic_id_a': left, 'topic_id_b': right,
                'title_a': by_id[left]['headline_pl'], 'title_b': by_id[right]['headline_pl'],
                **scores, 'difference': scores['title_description'] - scores['current'],
                'threshold': threshold, 'same_generation': by_id[left]['generation'] == by_id[right]['generation']})
    simulations = {}
    for n in range(35, 96):
        threshold = n / 100
        variants = {}
        for variant in VARIANTS:
            edges = {tuple(sorted((p['topic_id_a'], p['topic_id_b']))): p[variant] for p in pairs
                     if p['same_generation'] and p[variant] >= ai.embedding_pair_threshold(
                         p['topic_id_a'], p['topic_id_b'], threshold, ukraine_ids)}
            groups = ai.build_anchored_embedding_groups(ids, edges, threshold=threshold, ukraine_ids=ukraine_ids)
            grouped = {tid for group in groups for tid in group['topic_ids']}
            partition = [g['topic_ids'] for g in groups] + [[tid] for tid in ids if tid not in grouped]
            variants[variant] = {'qualifying_pairs': len(edges), 'groups': partition, 'group_count': len(partition)}
        simulations[f'{threshold:.2f}'] = variants
    return {'created_at': stamp(), 'snapshot_started_at': started_at,
            'model': ai.TOPIC_MERGE_EMBEDDING_MODEL, 'dimensions': ai.TOPIC_MERGE_EMBEDDING_DIMENSIONS,
            'threshold': ai.TOPIC_MERGE_EMBEDDING_MIN_SIMILARITY,
            'usage': usage, 'unique_embedding_inputs': len(vectors), 'topics': topics,
            'inputs': inputs, 'vectors': vectors, 'pairs': pairs, 'simulations': simulations}


def write_report(report, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    with (output / 'pairs.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        fields = ('title_a', 'title_b', 'current', 'title_description', 'difference', 'threshold',
                  'same_generation', 'topic_id_a', 'topic_id_b')
        writer = csv.DictWriter(handle, fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows({key: (round(row[key], 6) if isinstance(row[key], float) else row[key])
                         for key in fields} for row in report['pairs'])
    # Escape '<' even inside JSON to prevent a stored title closing the script element.
    display = {k: v for k, v in report.items() if k != 'vectors'}
    data = json.dumps(display, ensure_ascii=False).replace('<', '\\u003c')
    template = Path(__file__).with_name('embedding_comparison_report.html').read_text()
    (output / 'report.html').write_text(template.replace('__REPORT_JSON__', data))
    lines = ['# Porównanie embeddingów', '',
             f"Model: {report['model']}, wymiary: {report['dimensions']}; "
             f"wątków: {len(report['topics'])}, par: {len(report['pairs'])}.", '',
             '| Wątek A | Wątek B | Obecny | Tytuł + opis | Różnica |', '|---|---|---:|---:|---:|']
    for p in report['pairs']:
        clean = lambda s: s.replace('|', '/').replace('\n', ' ')
        lines.append(f"| {clean(p['title_a'])} | {clean(p['title_b'])} | {p['current']:.6f} | "
                     f"{p['title_description']:.6f} | {p['difference']:+.6f} |")
    lines += ['', 'Pełne dane i samodzielny raport HTML są w artefakcie tego przebiegu.',
              'To symulacja: nie zapisuje niczego w Supabase i nie zmienia progów ani wątków.']
    (output / 'summary.md').write_text('\n'.join(lines) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topic-ids', default='', help='Puste = 8 wątków Francji ze zrzutów.')
    parser.add_argument('--output', type=Path, default=Path('embedding-comparison'))
    args = parser.parse_args()
    ids = parse_topic_ids(args.topic_ids)
    started = stamp()
    topics = load_topics(SupabaseRestClient(), ids)
    inputs, texts = prepare_inputs(topics)
    print(f'[COMPARE] Wątków: {len(topics)}; wariantów: 2; tekstów do embeddingu: {len(texts)}. '
          'Bez treści artykułów, zapytań GPT i zmian w bazie.', flush=True)
    if any(t['status'] != 'ACTIVE' for t in topics):
        print('[COMPARE] Uwaga: część wybranych wątków zmieniła status; porównuję wskazane ID bez przekierowywania.', flush=True)
    from openai import OpenAI
    client = OpenAI(api_key=ai.openai_api_key(), timeout=ai.TOPIC_MERGE_EMBEDDING_REQUEST_TIMEOUT_SECONDS, max_retries=0)
    vectors, usage = request_vectors(client, texts)
    report = build_report(topics, inputs, vectors, usage, started)
    write_report(report, args.output)
    print(f'[COMPARE] Gotowe: {len(report["pairs"])} par, tokeny: {usage}. Raport: {args.output}.', flush=True)
    print('[COMPARE_RESULT] ' + json.dumps({k: v for k, v in report.items()
        if k in ('created_at', 'model', 'dimensions', 'usage', 'unique_embedding_inputs', 'pairs')}, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
