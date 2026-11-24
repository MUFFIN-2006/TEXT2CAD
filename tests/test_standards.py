import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from solidworks_mcp.agent.local_agent import LocalCADAgent
from solidworks_mcp.agent.offline_standards import prepare_snapshot
from solidworks_mcp.agent.standards import design_reference, lookup_dimensions
from solidworks_mcp.com_adapter.mock_adapter import MockSolidWorksAdapter


class StandardSheetsTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name, "test.sldedb")
        db = sqlite3.connect(path)
        db.executescript("""
            CREATE TABLE Standards(Name, enabled, TableNamePrefix, DefaultUnits, TypeID, CategoryID);
            INSERT INTO Standards VALUES ('Ansi Metric',1,'AM_','MILLIMETER','AM_Types','AM_Categories');
            CREATE TABLE AM_Categories(Name,TypeID,enabled);
            INSERT INTO AM_Categories VALUES('Washers','AM_TYPE_WASHERS',1);
            CREATE TABLE AM_Types(ID,Name);
            INSERT INTO AM_Types VALUES(2,'Plain Washers');
            CREATE TABLE AM_TYPE_WASHERS(key,ID,Name,Title,DataTable,ConfigurationTable,DataTableUnits,enabled);
            INSERT INTO AM_TYPE_WASHERS VALUES(2,2,'Regular','Regular Flat Washer - ANSI B18.22M','+W','+C','',1);
            CREATE TABLE AM_C(Grid_Item_Name,AltDataSource);
            INSERT INTO AM_C VALUES('','+UNRELATED');
            CREATE TABLE AM_W(SIZE,INSID_DIA,OUTSID_DIA,THICKNESS,enabled);
            INSERT INTO AM_W VALUES('8','9','26','2',1),('12','13','35','3',0);
        """)
        db.close()
        env = patch.dict(os.environ, SOLIDWORKS_TOOLBOX_DB=str(path))
        env.start()
        self.addCleanup(env.stop)

    def test_exact_rows_and_unavailable_sizes(self):
        reference = design_reference("M8 regular flat washer B18.22M")
        self.assertEqual(reference["table"], "AM_W")
        self.assertEqual(reference["rows"][0]["OUTSID_DIA"], "26")
        self.assertEqual(reference["length_unit"], "MILLIMETER")
        self.assertEqual(design_reference("M12 regular flat washer")["status"], "no_match")
        self.assertEqual(lookup_dimensions("B16.5")["status"], "no_match")
        self.assertEqual(lookup_dimensions(family_id="AM_TYPE_WASHERS:2", filters={"bogus":"8"})["status"], "error")

    def test_plan_uses_values_from_configured_sheet(self):
        agent = LocalCADAgent(MockSolidWorksAdapter())
        result = agent.run("plan a new ANSI M8 regular flat washer")
        self.assertEqual(result["status"], "planned", result["message"])
        self.assertEqual(result["operations"], [])
        self.assertEqual([s["arguments"]["radius"] for s in result["plan"] if s["operation"] == "sketch_circle"], [13, 4.5])
        self.assertEqual(result["plan"][-1]["arguments"]["depth"], 2)
        self.assertEqual(result["dimension_sources"][0]["designation"], "B18.22M")

    def test_custom_washer_measurements_in_request_or_size_reply(self):
        agent = LocalCADAgent(MockSolidWorksAdapter(), planner=Mock())
        direct = agent.run("plan a new M8 regular flat washer with a custom thickness of 3 mm and 22 mm OD")
        start = agent.run("plan a new metric regular flat washer with 22 mm OD")
        self.assertEqual(start["missing_fields"], ["nominal_size"])
        session = start["conversation_id"]
        bad = agent.run("M8 with 30 mm bore", session)
        self.assertEqual(bad["status"], "needs_input")
        self.assertIn("bore smaller", bad["message"])
        followup = agent.run("M8, use a thickness of 3 mm", session)
        self.assertEqual(followup["plan"], direct["plan"])
        self.assertEqual([s["arguments"]["radius"] for s in followup["plan"] if s["operation"] == "sketch_circle"],
                         [11, 4.5])
        self.assertEqual(followup["plan"][-1]["arguments"]["depth"], 3)
        source = followup["dimension_sources"][0]
        self.assertEqual(source["custom_dimensions_mm"], {"outer_diameter": 22, "thickness": 3})
        self.assertEqual(source["rows"][0]["THICKNESS"], "2")
        self.assertIn("Custom model dimensions", followup["message"])
        self.assertEqual(agent.run("build plan", session)["status"], "success")
        standard = agent.run("plan a new M8 regular flat washer")
        self.assertEqual(standard["plan"][-1]["arguments"]["depth"], 2)
        self.assertNotIn("custom_dimensions_mm", standard["dimension_sources"][0])

        start = agent.run("plan a new metric regular flat washer", separate=True, dimensions={"outer_diameter": 22})
        structured = agent.run("M8", start["conversation_id"], dimensions={"thickness": 3}, separate=True)
        self.assertEqual(structured["plan"], direct["plan"])

    def test_named_change_revises_dimension_while_design_is_pending(self):
        agent = LocalCADAgent(MockSolidWorksAdapter(), planner=Mock())
        start = agent.run("plan a new bracket with thickness of 4 mm")
        self.assertEqual(start["status"], "needs_input", start["message"])
        session = start["conversation_id"]
        revised = agent.run("change the thickness to 7 mm and use a width of 60 mm", session)
        self.assertEqual(revised["status"], "needs_input")
        self.assertNotIn("width", revised["missing_fields"])
        complete = agent.run("use defaults", session)
        self.assertEqual(complete["status"], "planned", complete["message"])
        self.assertEqual(complete["plan"][0]["arguments"]["thickness"], 7)
        self.assertEqual(complete["plan"][0]["arguments"]["width"], 60)

    def test_specific_edition_and_missing_designation_do_not_build(self):
        agent = LocalCADAgent(MockSolidWorksAdapter())
        for prompt in ("make a new M8 regular flat washer per ASME B18.22M-1981",
                       "make a new flange per ASME B16.5"):
            reply = agent.run(prompt)
            self.assertEqual(reply["status"], "error")
            self.assertFalse(reply["operations"])
            self.assertIn("sheet", reply["message"])

    def test_snapshot_lookup_survives_removal_of_original_database(self):
        source = Path(os.environ["SOLIDWORKS_TOOLBOX_DB"])
        target = source.with_name("toolbox.sqlite")
        prepare_snapshot(source, target)
        source.unlink()
        with patch("solidworks_mcp.agent.offline_standards.DIRECTORY", target.parent), patch.dict(os.environ):
            del os.environ["SOLIDWORKS_TOOLBOX_DB"]
            with patch("socket.socket.connect", side_effect=AssertionError("unexpected network access")):
                result = design_reference("M8 regular flat washer")
                self.assertEqual(result["database"], str(target))
                self.assertEqual(result["rows"][0]["OUTSID_DIA"], "26")
                self.assertEqual(lookup_dimensions(library="all")["total"], 1)
                self.assertEqual(lookup_dimensions(library="DIN")["total"], 0)

    def test_bare_guide_topic_and_explicit_search_preserve_reviewed_plan(self):
        folder = Path(os.environ["SOLIDWORKS_TOOLBOX_DB"]).parent
        guide = folder / "Tsubaki-Roller-Chain-Catalog.pdf"
        guide.touch()
        planner = Mock()
        agent = LocalCADAgent(MockSolidWorksAdapter(), planner=planner)
        plan = agent.run("plan a new block 20 x 10 x 6 on front plane")
        self.assertEqual(plan["status"], "planned")
        session = plan["conversation_id"]
        with patch("solidworks_mcp.agent.offline_standards.DIRECTORY", folder):
            original = agent.run("offline standards roller chain", session)
            for prompt in ("roller chain", "look up roller chain"):
                self.assertEqual(agent.run(prompt, session), original)
        self.assertEqual(original["status"], "success")
        self.assertEqual(original["operations"], [])
        self.assertIn(str(guide), [doc["path"] for doc in original["data"]["documents"]])
        self.assertEqual(agent.run("build plan", session)["status"], "success")
        planner.translate.assert_not_called()

    def test_design_request_and_pending_answer_take_precedence_over_guide_search(self):
        planner = Mock()
        planner.translate.side_effect = [("question", "Which chain type?"), ("question", "What pitch?")]
        agent = LocalCADAgent(MockSolidWorksAdapter(), planner=planner)
        with patch("solidworks_mcp.agent.local_agent.offline_inventory") as search:
            first = agent.run("make a roller chain")
            self.assertEqual(first["status"], "needs_input")
            session = first["conversation_id"]
            search.assert_not_called()
            search.return_value = dict(status="success", families=1, total=0, page_matches=[])
            self.assertEqual(agent.run("look up roller chain", session)["status"], "success")
            search.assert_called_once_with("roller chain")
            search.reset_mock()
            answer = agent.run("roller chain", session)
            self.assertEqual(answer["status"], "needs_input")
            self.assertIn("What pitch?", answer["message"])
            messages = planner.translate.call_args.args[0]
            self.assertEqual([m["content"] for m in messages if m["role"] == "user"],
                             ["make a roller chain", "roller chain"])
            search.assert_not_called()
