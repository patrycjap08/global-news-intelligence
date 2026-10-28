#!/usr/bin/env python3
"""Bounded production discovery/extraction probes, without AI or database writes."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
from types import SimpleNamespace
import time

import yaml
import article_harvester as harvest
import source_tester as sources


def audit_source(source, defaults, *, probes=2, browser=False):
    started = time.monotonic()
    result = {'source_id': source['id'], 'source_name': source['name'], 'homepage_status': None,
              'candidate_count': 0, 'notes': [], 'articles': [], 'error': None}
    playwright = context = engine = None
    try:
        page = None
        if browser:
            from playwright.sync_api import sync_playwright
            playwright = sync_playwright().start()
            engine = playwright.chromium.launch(headless=True)
            context = engine.new_context()
            page = context.new_page()
        client = sources.HttpClient(float(source.get('timeout_seconds', defaults.get('timeout_seconds', 15))),
                                    int(defaults.get('min_delay_ms', 500)), max_retries=0)
        args = SimpleNamespace(browser=browser, max_sitemap_probes=6, max_sitemap_children=3,
                               discovery_limit_per_source=500)
        home, candidates, notes = harvest.discover_candidates(client, source, defaults, args, page)
        result.update(homepage_status=home.status, candidate_count=len(candidates), notes=notes)
        for candidate in candidates[:max(1, probes)]:
            if candidate.get('api_body'):
                text = candidate['api_body']
                extracted = {'title': candidate.get('api_title') or candidate.get('title_hint'),
                             'body_success': True, 'word_count': len(text.split()), 'status': 200}
                method = candidate.get('api_method', 'WORDPRESS_API')
            else:
                extracted, method = harvest.fetch_one(client, page, source, candidate['url'], browser)
            result['articles'].append({'url': candidate['url'], 'title': extracted.get('title'),
                'status': extracted.get('status'), 'classification': harvest.classify_item(extracted)[1],
                'words': int(extracted.get('word_count') or 0), 'method': method})
    except Exception as exc:
        result['error'] = str(exc)[:400]
    finally:
        if context:
            context.close()
        if engine:
            engine.close()
        if playwright:
            playwright.stop()
    result['seconds'] = round(time.monotonic() - started, 1)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('sources.yaml'))
    parser.add_argument('--runtime-config', type=Path, default=Path('source_runtime.yaml'))
    parser.add_argument('--source', action='append', help='Source ID; repeat to check multiple sources.')
    parser.add_argument('--probes', type=int, default=2)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--browser', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('source_audit_results.json'))
    args = parser.parse_args()
    defaults, configured = sources.load_config(args.config)
    runtime = yaml.safe_load(args.runtime_config.read_text()) if args.runtime_config.exists() else {}
    runtime = {row['id']: row for row in (runtime or {}).get('sources', [])}
    selected = set(args.source or [])
    enabled = [s for s in configured if sources.source_is_enabled(s)]
    if selected - {s['id'] for s in enabled}:
        parser.error('Unknown or disabled sources: ' + ', '.join(sorted(selected - {s['id'] for s in enabled})))
    enabled = [s for s in enabled if not selected or s['id'] in selected]
    for source in enabled:
        for field in ('discovery_method', 'content_method', 'technical_status'):
            if not source.get(field) and runtime.get(source['id'], {}).get(field):
                source[field] = runtime[source['id']][field]
    reports = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 4))) as pool:
        futures = [pool.submit(audit_source, s, defaults, probes=args.probes, browser=args.browser) for s in enabled]
        for future in as_completed(futures):
            result = future.result()
            reports.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sorted(reports, key=lambda r: r['source_id']), ensure_ascii=False, indent=2) + '\n')
    # Availability is evidence, not a CI pass/fail guarantee. Blocked sources
    # remain explicit in the report; the action itself checks no production data.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
