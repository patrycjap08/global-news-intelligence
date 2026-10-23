"""Finished writer responses for tests; metadata does not add display text."""


def article_response(paragraphs, context_spans=()):
    return {
        'summary_pl': '\n\n'.join(p['text_pl'] for p in paragraphs),
        'paragraph_sources': [{'fact_ids': p['fact_ids']} for p in paragraphs],
        'context_spans': list(context_spans),
    }
