"""Read-only summary eligibility report; never calls AI or writes to Supabase."""
from collections import Counter, defaultdict
import json

from ai_pipeline import distinct_source_keys, has_independent_source
from supabase_client import SupabaseRestClient

TARGET_IDS = {
    'topic_ecc6a50eeb25c58e842235aa', 'topic_dcb35f2c846d6d0ccf9254b6',
    'topic_91677e5ed015f208b6767faf', 'topic_71bc7f1265a14e2445c3ebcf',
    'topic_12714cf20ff37d1afaa82390', 'topic_94c90400e36d96d3b89d5a40',
    'topic_20e4df0041f7530ea57975ec', 'topic_37da6bdb7f676f73096d1c79',
}


def main():
    client = SupabaseRestClient()
    topics = client.select_all('topics', filters=[('status', 'eq.ACTIVE')])
    links = client.select_all('topic_articles', columns='topic_id,article_id')
    summaries = client.select_all('topic_summaries', columns='topic_id,summary,input_hash,version,updated_at')
    assignments = client.select_all('article_topic_assignments', columns='topic_id,article_id,created_at')
    articles = client.select_all('articles', columns='article_id,source_id,source_name,source_profile,source_type')
    by_id = {row['article_id']: row for row in articles}
    by_topic = defaultdict(list)
    for row in links:
        by_topic[row['topic_id']].append(row['article_id'])
    previous = {row['topic_id']: row for row in summaries}
    times = {(row['topic_id'], row['article_id']): str(row.get('created_at') or '') for row in assignments}
    latest = defaultdict(str)
    for row in assignments:
        key = row['topic_id']
        latest[key] = max(latest[key], str(row.get('created_at') or ''))
    topic_ids = {row['topic_id'] for row in topics}
    print('Odczyt całych tabel:', json.dumps({
        'topics': len(topics), 'unique_topics': len(topic_ids),
        'links': len(links), 'unique_links': len({(r['topic_id'],r['article_id']) for r in links}),
        'summaries': len(summaries), 'assignments': len(assignments), 'articles': len(articles),
    }), flush=True)
    direct = client.select_all('topics', filters=[('topic_id', 'in.('+','.join(sorted(TARGET_IDS))+')')])
    for topic in direct:
        tid = topic['topic_id']
        ids = list(dict.fromkeys(by_topic[tid]))
        old = previous.get(tid)
        updated = str((old or {}).get('updated_at') or '')
        new_ids = [aid for aid in ids if not old or times.get((tid, aid), '') > updated]
        rows = [by_id[aid] for aid in ids if aid in by_id]
        if tid not in topic_ids:
            reason = 'BRAK W ODCZYCIE AKTYWNYCH TEMATÓW'
        elif len(ids) < 2:
            reason = 'MNIEJ NIŻ DWA POWIĄZANIA'
        elif old and latest[tid] <= updated:
            reason = 'ZNACZNIK SYNTEZY NOWSZY OD PRZYPISAŃ'
        elif not new_ids:
            reason = 'BRAK NOWYCH ARTYKUŁÓW WEDŁUG PRZYPISAŃ'
        elif not any(aid in by_id for aid in new_ids) or len(rows) < 2:
            reason = 'BRAK ARTYKUŁÓW W ODCZYCIE'
        elif len(distinct_source_keys(rows)) < 2:
            reason = 'TYLKO JEDNO ŹRÓDŁO'
        elif not has_independent_source(rows):
            reason = 'WYŁĄCZNIE ŹRÓDŁA PAŃSTWOWE'
        else:
            reason = 'KWALIFIKUJE SIĘ DO SYNTEZY'
        direct_links = client.select_all('topic_articles', columns='topic_id,article_id', filters=[('topic_id', 'eq.'+tid)])
        print(topic['headline_pl'], json.dumps({
            'result': reason, 'status': topic['status'], 'links_from_full_read': len(ids),
            'links_from_direct_read': len(direct_links), 'article_rows': len(rows),
            'sources': sorted({r['source_name'] for r in rows}),
            'summary_row_exists': bool(old), 'summary_updated_at': updated,
            'latest_assignment': latest[tid], 'new_article_count': len(new_ids),
        }, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
