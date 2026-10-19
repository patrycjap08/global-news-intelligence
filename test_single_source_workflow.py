import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import news_pipeline as pipeline
from source_tester import load_config


ROOT = Path(__file__).parent


def workflow(name):
    # GitHub uses YAML 1.2; BaseLoader keeps its "on" key out of YAML 1.1 booleans.
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


class SingleSourcePipelineTests(unittest.TestCase):
    def run_pipeline(self, source=None, result=None):
        events = []
        with tempfile.TemporaryDirectory() as folder, contextlib.ExitStack() as stack:
            argv = ["news_pipeline.py", "--db", str(Path(folder) / "articles.sqlite3"),
                    "--config", str(ROOT / "sources.yaml"), "--browser", "--retry-rejected",
                    "--ai-max-articles", "0", "--ai-batch-size", "25"]
            if source is not None:
                argv.extend(["--source", source])
            stack.enter_context(patch("sys.argv", argv))
            client = stack.enter_context(patch.object(pipeline, "SupabaseRestClient")).return_value
            stack.enter_context(patch.object(pipeline, "log"))
            stack.enter_context(patch.object(pipeline, "pull_state", side_effect=lambda *a: events.append("pull") or {}))
            stack.enter_context(patch.object(pipeline, "latest_run_id", return_value="selected_source_run"))
            harvest = stack.enter_context(patch.object(pipeline.subprocess, "run", side_effect=lambda *a, **kw: events.append("harvest")))
            push = stack.enter_context(patch.object(pipeline, "push_run", side_effect=lambda *a: events.append("push") or {}))
            analyze = stack.enter_context(patch.object(pipeline, "analyze_run", side_effect=lambda *a, **kw: events.append("ai") or (result or {})))
            status = pipeline.main()
            self.assertEqual(events, ["pull", "harvest", "push", "ai"])
            self.assertEqual(harvest.call_count, 1)
            self.assertEqual(push.call_args.args[1:], ("selected_source_run", client))
            self.assertEqual(analyze.call_args.args[1:], ("selected_source_run", client))
            self.assertEqual(analyze.call_args.kwargs, {
                "max_articles": 0, "batch_size": 25,
                "merge_existing_summaries_mode": False, "merge_existing_max_topics": 0,
            })
            return status, harvest.call_args.args[0]

    def test_one_source_limits_harvesting_and_keeps_the_whole_ai_stage(self):
        status, command = self.run_pipeline("Zero.pl")
        self.assertEqual(status, 0)
        self.assertEqual(command.count("--source"), 1)
        self.assertEqual(command[command.index("--source") + 1], "zero_pl")
        self.assertIn("article_harvester.py", command)
        self.assertIn("--browser", command)
        self.assertIn("--retry-rejected", command)

    def test_full_without_source_keeps_all_source_harvest(self):
        status, command = self.run_pipeline()
        self.assertEqual(status, 0)
        self.assertNotIn("--source", command)

    def test_one_source_does_not_mask_ai_failures(self):
        status, _ = self.run_pipeline("zero_pl", {"failed_summaries": 1})
        self.assertEqual(status, 1)

    def test_ids_and_names_resolve_to_exactly_one_enabled_source(self):
        for value in ("zero_pl", "Zero.pl", " ZERO.PL "):
            self.assertEqual(pipeline.resolve_harvest_source(ROOT / "sources.yaml", value)["id"], "zero_pl")

    def test_invalid_or_incompatible_selection_fails_before_database_access(self):
        _, sources = load_config(ROOT / "sources.yaml")
        disabled = next(source["id"] for source in sources if not source.get("enabled", True))
        for selection, flags in (("", []), ("not-a-source", []), (disabled, []),
                                 ("zero_pl", ["--ai-only"]), ("zero_pl", ["--titles-only"])):
            with self.subTest(selection=selection, flags=flags), patch("sys.argv", [
                "news_pipeline.py", "--config", str(ROOT / "sources.yaml"), "--source", selection, *flags,
            ]), patch.object(pipeline, "SupabaseRestClient") as client, \
                    patch.object(pipeline.subprocess, "run") as harvest, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    pipeline.main()
                self.assertEqual(error.exception.code, 2)
                client.assert_not_called()
                harvest.assert_not_called()


class SingleSourceWorkflowTests(unittest.TestCase):
    def test_dropdown_matches_all_enabled_catalog_entries(self):
        _, sources = load_config(ROOT / "sources.yaml")
        field = workflow("harvest-source.yml")["on"]["workflow_dispatch"]["inputs"]["source"]
        expected = [source["name"] for source in sources if source.get("enabled", True)]
        self.assertEqual(field["type"], "choice")
        self.assertEqual(field["required"], "true")
        self.assertEqual(field["options"], expected)
        self.assertEqual(len(set(expected)), len(expected))
        self.assertIn(field["default"], expected)
        for name in field["options"]:
            self.assertTrue(pipeline.resolve_harvest_source(ROOT / "sources.yaml", name))

    def test_execution_settings_queue_export_and_pages_are_shared(self):
        single = workflow("harvest-source.yml")
        main = workflow("harvest.yml")
        job = single["jobs"]["harvest"]
        self.assertEqual(job["uses"], "./.github/workflows/harvest.yml")
        self.assertEqual(job["with"]["mode"], "single-source")
        self.assertEqual(job["with"]["source"], "${{ inputs.source }}")
        self.assertEqual(job["secrets"], "inherit")
        self.assertIn("source", main["on"]["workflow_call"]["inputs"])
        self.assertEqual(main["concurrency"]["group"], "global-news-harvest")
        self.assertEqual(main["concurrency"]["cancel-in-progress"], "false")
        self.assertNotIn("concurrency", single)
        steps = main["jobs"]["harvest"]["steps"]
        self.assertTrue(any(step.get("id") == "public_export" and "always()" in step["if"] for step in steps))
        self.assertTrue(any(step.get("with", {}).get("name") == "gni-public-data" for step in steps))
        triggers = workflow("deploy-pages.yml")["on"]["workflow_run"]["workflows"]
        self.assertIn(single["name"], triggers)
        self.assertIn(main["name"], triggers)

    def test_shell_passes_selection_literally_and_does_not_drop_empty_selection(self):
        steps = workflow("harvest.yml")["jobs"]["harvest"]["steps"]
        script = next(step["run"] for step in steps if step.get("name") == "Run ingestion, sync and AI")
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / "must-not-be-created"
            for selection in ("Zero.pl", "", f"Zero.pl; touch {marker}"):
                with self.subTest(selection=selection):
                    env = {**os.environ, "RUN_MODE": "single-source", "HARVEST_SOURCE": selection,
                           "RETRY_REJECTED": "false", "HARVEST_DAILY_MAX_ARTICLES_PER_SOURCE": "0",
                           "HARVEST_TOP_ARTICLES_PER_SOURCE_PER_RUN": "10", "AI_MAX_ARTICLES_PER_RUN": "0",
                           "AI_BATCH_SIZE": "25"}
                    result = subprocess.run(["bash", "-c", "python() { printf '%s\\0' \"$@\"; }\n" + script],
                                            env=env, capture_output=True, check=True)
                    args = result.stdout.decode().split("\0")[:-1]
                    self.assertEqual(args[args.index("--source") + 1], selection)
                    self.assertIn("--browser", args)
                    self.assertNotIn("--ai-only", args)
                    self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
