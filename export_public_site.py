#!/usr/bin/env python3
"""Export only public app views to immutable, lazy-loaded Pages snapshots."""
import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from supabase_client import SupabaseRestClient

ARTICLE_COLUMNS = 'article_id,source_id,source_name,source_profile,source_type,title,original_url,published_at,fetched_at,word_count'

def load_export(path):
    if path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
    else:
        rows = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(rows, list) or not rows:
        raise ValueError('Eksport jest pusty lub nie jest listą wierszy.')
    return [json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload'] for row in rows]

def select_ids(client, table, column, ids, columns='*'):
    result = []
    ids = sorted(set(ids))
    for start in range(0, len(ids), 80):
        filters = [(column, 'in.(' + ','.join(ids[start:start+80]) + ')')]
        offset = 0
        while True:
            page = client.select(table, columns=columns, filters=filters, order=f'{column}.asc', limit=500, offset=offset)
            result.extend(page)
            if len(page) < 500:
                break
            offset += len(page)
    return result

def from_database(client):
    topics = client.select_all('app_topics', filters=[('source_count', 'gte.2')])
    ids = [t['topic_id'] for t in topics]
    links = select_ids(client, 'app_topic_articles', 'topic_id', ids)
    articles = select_ids(client, 'app_articles', 'article_id', [l['article_id'] for l in links], ARTICLE_COLUMNS)
    summaries = select_ids(client, 'app_topic_summaries', 'topic_id', ids)
    legacy = [s['topic_id'] for s in summaries if not isinstance(s.get('summary', {}).get('updates'), list)]
    history = select_ids(client, 'app_topic_summary_versions', 'topic_id', legacy,
                         'topic_id,version,generated_at,updates:summary->updates,latest_update:summary->latest_update,update:summary->update')
    latest = client.select('app_latest_harvest', columns='started_at', limit=1)
    stamp = datetime.now(timezone.utc).isoformat()
    link_map, summary_map, history_map, article_map = {}, {}, {}, {a['article_id']: a for a in articles}
    for l in links:
        link_map.setdefault(l['topic_id'], []).append(l)
    for s in summaries:
        summary_map[s['topic_id']] = s
    for h in history:
        h['summary'] = {k: h.pop(k, None) for k in ('updates', 'latest_update', 'update')}
        history_map.setdefault(h['topic_id'], []).append(h)
    return [dict(schema=1, expected_topics=len(topics), exported_at=stamp,
                 latest_harvest_started_at=latest[0]['started_at'] if latest else None,
                 topic=t, links=link_map.get(t['topic_id'], []),
                 articles=[article_map[l['article_id']] for l in link_map.get(t['topic_id'], []) if l['article_id'] in article_map],
                 summary=summary_map.get(t['topic_id']), history=history_map.get(t['topic_id'], [])) for t in topics]

def write_site(rows, target):
    if not rows:
        raise ValueError('Brak danych; poprzedni eksport zostanie zachowany.')
    expected = rows[0]['expected_topics']
    ids = [row['topic']['topic_id'] for row in rows]
    if len(rows) != expected or len(set(ids)) != expected:
        raise ValueError(f'Niekompletny eksport: {len(rows)} wierszy zamiast {expected}. Ustaw większy limit w SQL Editor.')
    if any(row.get('schema') != 1 or row['expected_topics'] != expected or row['exported_at'] != rows[0]['exported_at'] for row in rows):
        raise ValueError('Wiersze nie pochodzą z jednego poprawnego eksportu.')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', tid) for tid in ids):
        raise ValueError('Niepoprawny identyfikator wątku.')
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    generation = hashlib.sha256(raw.encode()).hexdigest()[:20]
    # Only explicit public-view fields are emitted. Never serialize API keys/body.
    articles, links, previews = {}, [], []
    topic_fields = 'topic_id headline_pl status first_seen_at last_seen_at article_count source_count coverage_status needs_review merged_into_topic_id merged_at updated_at categories is_current'.split()
    topic_rows = []
    details = {}
    for row in rows:
        tid = row['topic']['topic_id']
        topic_rows.append({k: row['topic'].get(k) for k in topic_fields})
        for article in row['articles']:
            articles[article['article_id']] = {k: article.get(k) for k in ARTICLE_COLUMNS.split(',')}
        links.extend({k: l.get(k) for k in ('topic_id', 'article_id', 'confidence')} for l in row['links'])
        summary = row.get('summary')
        if summary:
            stored = summary['summary'] or {}
            base = stored.get('base_summary') or stored
            update = stored.get('latest_update') or stored.get('update') or {}
            previews.append(dict(topic_id=tid, version=summary['version'], updated_at=summary.get('updated_at'),
                                 summary={'base_summary': {'topic': base.get('topic', {}), 'summary_pl': (base.get('summary_pl') or '')[:650]},
                                          'latest_update': update, 'last_analysis': stored.get('last_analysis', {})}))
        details[tid] = {'summary': summary, 'history': row.get('history', [])}
    if any(l['article_id'] not in articles or l['topic_id'] not in ids for l in links):
        raise ValueError('Eksport ma brakujące artykuły lub obce przypisania.')
    target.mkdir(parents=True, exist_ok=True)
    folder = target / generation / 'topics'
    folder.mkdir(parents=True, exist_ok=True)
    for tid, detail in details.items():
        (folder / f'{tid}.json').write_text(json.dumps(detail, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    index = dict(schema=1, generation=generation, exported_at=rows[0]['exported_at'],
                 latest_harvest_started_at=rows[0].get('latest_harvest_started_at'),
                 topics=topic_rows, articles=list(articles.values()), links=links, summaries=previews)
    tmp = target / 'index.json.tmp'
    tmp.write_text(json.dumps(index, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    tmp.replace(target / 'index.json')
    return index

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, help='Eksport CSV/JSON z SQL Editor; bez odczytu API.')
    parser.add_argument('--output', type=Path, default=Path('public_site_data'))
    args = parser.parse_args()
    rows = load_export(args.input) if args.input else from_database(SupabaseRestClient())
    index = write_site(rows, args.output)
    print(f"Eksport strony: {len(index['topics'])} wątków, {len(index['articles'])} artykułów; {index['generation']}.")

if __name__ == '__main__':
    main()
