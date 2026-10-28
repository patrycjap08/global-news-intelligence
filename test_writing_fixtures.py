"""Finished writer responses for tests; metadata does not add display text."""


def article_response(paragraphs, context_spans=(), *, brief_paragraphs=None):
    if brief_paragraphs is None:
        # Legacy tests exercise the full article. Dedicated brief tests supply
        # curated text; these defaults only satisfy the expanded JSON shape.
        brief_paragraphs = [{'text_pl': p['text_pl'], 'fact_ids': p['fact_ids']}
                            for p in paragraphs if p['fact_ids']][:2]
        if len(brief_paragraphs) == 1:
            brief_paragraphs.append(dict(brief_paragraphs[0]))
    return {
        'summary_pl': '\n\n'.join(p['text_pl'] for p in paragraphs),
        'brief_paragraphs': brief_paragraphs,
        'paragraph_sources': [{'fact_ids': p['fact_ids']} for p in paragraphs],
        'context_spans': list(context_spans),
    }
