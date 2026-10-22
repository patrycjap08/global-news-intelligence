import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import article_harvester as harvest
import news_pipeline as pipeline
import source_tester as sources
import ai_pipeline as ai
import perspective_summaries as perspectives


class DisabledStateSourceTests(unittest.TestCase):
    def test_catalog_disables_all_state_profiles_and_keeps_other_sources(self):
        _, catalog = sources.load_config(Path('sources.yaml'))
        state = [s for s in catalog if sources.infer_editorial_profile(s) in {'STATE_ALIGNED', 'STATE_MEDIA'}]
        self.assertEqual(len(state), 8)
        self.assertTrue(all(not s.get('enabled', True) and not sources.source_is_enabled(s) for s in state))
        for source in state:
            with self.subTest(source=source['id']), self.assertRaises(ValueError):
                pipeline.resolve_harvest_source(Path('sources.yaml'), source['id'])
        self.assertEqual(pipeline.resolve_harvest_source(Path('sources.yaml'), 'PAP')['id'], 'pap')
        self.assertEqual(pipeline.resolve_harvest_source(Path('sources.yaml'), 'South China Morning Post')['id'], 'south_china_morning_post')
        for private in ('Caixin', 'Kommersant'):
            self.assertTrue(sources.source_is_enabled(pipeline.resolve_harvest_source(Path('sources.yaml'), private)))
        for source_id in ('caixin', 'kommersant'):
            row = {'source_id': source_id, 'source_profile': 'STATE_ALIGNED'}
            self.assertFalse(ai.is_state_source(row))
            self.assertEqual(perspectives.article_group(row), 'RIGHT')

    def test_enabled_flag_cannot_bypass_state_profile_at_any_network_entrypoint(self):
        entry = {'id': 'custom_state', 'name': 'State', 'homepage': 'https://example.invalid',
                 'enabled': True, 'editorial_profile': 'STATE_ALIGNED', 'state_controlled': True}
        self.assertFalse(sources.source_is_enabled(entry))
        self.assertTrue(sources.source_is_enabled({**entry, 'state_controlled': False}), 'Alignment alone does not establish control')
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory, 'sources.yaml')
            config.write_text('sources:\n- id: custom_state\n  name: State\n  enabled: true\n  state_controlled: true\n  editorial_profile: STATE_ALIGNED\n  homepage: https://example.invalid\n')
            with patch('sys.argv', ['article_harvester.py', '--config', str(config), '--source', 'custom_state', '--runtime-config', str(Path(directory, 'missing'))]), patch.object(harvest, 'open_db') as db, patch.object(sources.HttpClient, 'get') as network:
                with self.assertRaises(SystemExit):
                    harvest.main()
                db.assert_not_called()
                network.assert_not_called()
            with patch('sys.argv', ['source_tester.py', '--config', str(config), '--source', 'custom_state']), patch.object(sources, 'test_source') as fetch, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(sources.main(), 2)
                fetch.assert_not_called()
            with self.assertRaises(ValueError):
                pipeline.resolve_harvest_source(config, 'State')


if __name__ == '__main__':
    unittest.main()
