import os
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from solidworks_mcp.agent.local_agent import LocalCADAgent
from solidworks_mcp.agent.codex_planner import CodexPlanner
from solidworks_mcp.com_adapter.base import BaseSolidWorksAdapter


class CodexRoutingTests(unittest.TestCase):
    def setUp(self):
        self.adapter = Mock(spec=BaseSolidWorksAdapter)
        self.planner = Mock()
        self.planner.available.return_value = True
        self.agent = LocalCADAgent(self.adapter, planner=self.planner)

    def test_catalog_search_and_codex_reference_on_followup(self):
        with TemporaryDirectory() as folder:
            path = Path(folder, "library.md")
            with patch.dict(os.environ, SOLIDWORKS_PARTS_LIBRARY=str(path)):
                path.write_text("### 01. Hardware\n* **Keys:** Woodruff keys (DIN 6888), feather keys.\n"
                                "06. Springs\n• Springs: Compression springs (closed, open ends).", encoding="utf-8")
                reply = self.agent.run("find part DIN6888")
                self.assertEqual(reply["data"]["matches"], ["Hardware / Keys — Woodruff keys (DIN 6888)"])
                pending = self.agent.run("add a hole")
                self.agent.run("find part springs", pending["conversation_id"])
                self.assertIn(pending["conversation_id"], self.agent.pending)
                history = [{"role":"user", "content":"plan a compression spring"},
                           {"role":"assistant", "content":"What length?"},
                           {"role":"user", "content":"20 mm"}]
                planner = CodexPlanner()
                planner.executable = "codex"
                planner.host = False
                def respond(args, **kwargs):
                    Path(args[args.index("-o")+1]).write_text(json.dumps({
                        "kind": "question", "text": "What wire diameter?"}), encoding="utf-8")
                    return Mock(returncode=0)
                with patch("solidworks_mcp.agent.codex_planner.subprocess.run", side_effect=respond) as run:
                    self.assertEqual(planner.translate(history), ("question", "What wire diameter?"))
                supplied = run.call_args.kwargs["input"]
                self.assertIn("Compression springs (closed, open ends)", supplied)
                self.assertNotIn("Woodruff", supplied)
                self.assertEqual(history[-1]["content"], "20 mm")
                path.write_text("04. Seals\n• Seals: X-rings (quad-rings).", encoding="utf-8")
                self.assertIn("X-rings", self.agent.run("find part quad-ring")["message"])
                path.unlink()
                self.assertEqual(self.agent.run("find part springs")["status"], "error")

    def test_model_clarification_stays_in_the_same_plan(self):
        self.planner.translate.side_effect = [
            ("question", "Which plane should the base be centered on?"),
            ("command", "make a new block 80 x 40 x 12 on top plane"),
        ]
        first = self.agent.run("codex I need a new 80 by 40 by 12 mm rectangular solid")
        self.assertEqual(first["status"], "needs_input")
        session = first["conversation_id"]
        reply = self.agent.run("Top plane", session)
        self.assertEqual(reply["status"], "planned", reply["message"])
        self.assertEqual(reply["plan"][1]["arguments"]["plane_or_face"], "Top Plane")
        messages = self.planner.translate.call_args.args[0]
        self.assertEqual([msg["role"] for msg in messages], ["user", "assistant", "user"])
        self.adapter.connect.assert_not_called()

    def test_plain_language_fallback_and_template_questions(self):
        self.planner.translate.return_value = ("command", "make a helical gear with 15 mm OD and 10 mm bore")
        first = self.agent.run("I'd like some helical teeth around a 10 mm bore, 15 mm across the tips")
        self.assertEqual(first["status"], "needs_input")
        result = self.agent.run("use defaults", first["conversation_id"])
        self.assertEqual(result["status"], "planned", result["message"])
        self.assertEqual(result["plan"][0]["arguments"]["bore_diameter"], 10)
        self.adapter.connect.assert_not_called()

    def test_literal_stays_local_and_model_cannot_launch_native_commands(self):
        self.planner.translate.return_value = ("command", "make a helical gear")
        self.assertEqual(self.agent.run("make a helical gear")["status"], "needs_input")
        self.planner.translate.assert_not_called()
        self.planner.translate.return_value = ("command", "run command LoftedBossBase")
        self.assertEqual(self.agent.run("codex plan my part")["status"], "error")
        self.adapter.connect.assert_not_called()

    def test_document_choice_comes_from_user_when_planner_paraphrases(self):
        from solidworks_mcp.com_adapter.mock_adapter import MockSolidWorksAdapter
        adapter = MockSolidWorksAdapter()
        adapter.new_part()
        agent = LocalCADAgent(adapter, planner=self.planner)
        self.planner.translate.return_value = ("command", "make a new block 80 x 40 x 12 on top plane")
        result = agent.run("make a rectangular fixture")
        self.assertEqual(result["status"], "success", result["message"])
        self.assertEqual(adapter.active_document, "Part1.SLDPRT")
        self.planner.translate.return_value = ("command", "make a block 80 x 40 x 12 on top plane")
        result = agent.run("make a new rectangular fixture")
        self.assertEqual(result["status"], "success", result["message"])
        self.assertEqual(adapter.active_document, "Part2.SLDPRT")

    def test_freeform_virtual_assembly_default_entry_and_active_part_edit(self):
        from solidworks_mcp.com_adapter.mock_adapter import MockSolidWorksAdapter
        adapter = MockSolidWorksAdapter()
        agent = LocalCADAgent(adapter, planner=self.planner)
        self.planner.translate.return_value = ("assembly", "Base at (0,0,0): block 80 x 40 x 6 on front plane\n"
                                              "Pin at (20,0,6): cylinder 6 mm diameter by 12 mm long on front plane")
        result = agent.run("make a fixture with an 80 mm base and a 6 mm pin")
        self.assertEqual(result["status"], "success", result["message"])
        self.assertEqual([f["origin"] for f in adapter.features], [(0,0,0), (20,0,6)])
        self.assertFalse(adapter._saved_components)
        adapter.new_part()
        doc = adapter.active_document
        self.planner.translate.return_value = ("command", "add a 12 x 8 mm pocket 3 mm deep at (0, 0) on front plane")
        result = agent.run("cut a little recess measuring 12 by 8 mm, 3 deep, centered on the front plane")
        if result["status"] == "planned":
            result = agent.run("build plan", result["conversation_id"])
        self.assertEqual(result["status"], "success", result["message"])
        self.assertEqual(adapter.active_document, doc)
