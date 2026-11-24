import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from solidworks_mcp.agent.local_agent import LocalCADAgent, Plan, Step
from solidworks_mcp.com_adapter.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.com_adapter.solidworks_com import SolidWorksCOMAdapter
from solidworks_mcp.com_adapter.threads import add_screw_mate, turn_fastener


class FastenerDialogueTests(unittest.TestCase):
    def setUp(self):
        offline = patch("solidworks_mcp.agent.codex_planner.CodexPlanner.available", return_value=False)
        offline.start()
        self.addCleanup(offline.stop)
        self.adapter = MockSolidWorksAdapter()
        self.agent = LocalCADAgent(self.adapter)

    def make_pair(self):
        start = self.agent.run("make a new M8 x 30 nut and bolt")
        built = self.agent.run("yes", start["conversation_id"])
        self.assertEqual(built["status"], "success", built["message"])
        self.adapter.features[0]["origin"] = (90, 0, 0)
        self.adapter.features[1]["origin"] = (10, 20, 30)
        return self.adapter.features

    def test_move_existing_bolt_to_rotated_nut_without_planning_or_creation(self):
        bolt, nut = self.make_pair()
        nut["rotation"] = (0,0,1, 0,1,0, -1,0,0)
        self.agent.planner = Mock()
        self.agent.pending["current"] = Plan([Step("codex_question", {"question": "Should I make a new pair?",
                                                                      "messages": []})], False)
        with patch.object(self.adapter, "new_assembly", side_effect=AssertionError("unexpected new assembly")), \
             patch.object(self.adapter, "new_part", side_effect=AssertionError("unexpected new part")):
            reply = self.agent.run("move bolt on the nut", "current")
            self.assertEqual(reply["status"], "success", reply["message"])
            self.assertEqual([s["tool"] for s in reply["operations"]], ["move_fastener"])
            self.assertEqual(bolt["origin"], (38.5, 20, 30))
            self.assertEqual(bolt["rotation"], nut["rotation"])
            self.assertEqual(nut["origin"], (10, 20, 30))
            self.assertEqual(len(self.adapter.features), 2)
            again = self.agent.run("move the bolt onto the nut", reply["conversation_id"])
            self.assertFalse(again["data"]["moved"])
            self.agent.planner.translate.assert_not_called()

    def test_add_pair_reuses_assembly_until_new_is_requested(self):
        self.adapter.new_assembly()
        for command, expected in (("make an M8 x 30 nut and bolt", "Assem1.SLDASM"),
                                  ("make a new M8 x 30 nut and bolt", "Assem2.SLDASM")):
            start = self.agent.run(command)
            result = self.agent.run("yes", start["conversation_id"])
            self.assertEqual(result["status"], "success", result["message"])
            self.assertEqual(self.adapter.active_document, expected)

    def test_rotate_on_nuts_thread_installs_one_screw_mate_on_previously_selected_pair(self):
        first = self.agent.run("make a new M8 x 20 nut and bolt")
        session = first["conversation_id"]
        self.assertEqual(self.agent.run("yes", session)["status"], "success")
        second = dict(self.adapter.features[0], name="M8x20-Bolt-2")
        self.adapter.features.append(second)
        move = self.agent.run("make bolt move on the nut", session)
        self.assertEqual(move["status"], "needs_input")
        self.assertEqual(self.agent.run("2", session)["data"]["component"], second["name"])
        for wording, created in (("it should rotate on the nuts thread", True), ("add a screw mate", False)):
            reply = self.agent.run(wording, session)
            self.assertEqual(reply["status"], "success", reply["message"])
            self.assertEqual([op["tool"] for op in reply["operations"]], ["screw_mate_fasteners"])
            self.assertEqual(reply["data"]["bolt"], second["name"])
            self.assertEqual(reply["data"]["pitch_mm"], 1.25)
            self.assertEqual(reply["data"]["created"], created)
        self.assertEqual(len([f for f in self.adapter.features if f["type"] == "Mate"]), 1)
        before = second["origin"]
        nut = self.adapter.features[1]
        fixed = nut["origin"]
        turn = self.agent.run("turn bolt a quarter turn", session)
        self.assertEqual(turn["status"], "success", turn["message"])
        self.assertAlmostEqual(second["origin"][2]-before[2], .3125)
        self.assertAlmostEqual(second["rotation"][0], 0)
        self.assertAlmostEqual(second["rotation"][1], 1)
        self.assertEqual(self.agent.run("turn bolt 90 degrees counterclockwise", session)["status"], "success")
        self.assertAlmostEqual(second["origin"][2], before[2])
        self.assertEqual(self.agent.run("turn bolt 200 turns", session)["status"], "error")
        self.assertEqual(nut["origin"], fixed)

    def test_move_asks_for_existing_instance_and_keeps_nut_fixed(self):
        bolt, nut = self.make_pair()
        extra = dict(bolt, name="M8x30-Bolt-2")
        self.adapter.features.append(extra)
        reply = self.agent.run("move bolt on the nut")
        session = reply["conversation_id"]
        self.assertEqual(reply["status"], "needs_input", reply["message"])
        self.assertIn(extra["name"], reply["message"])
        self.assertEqual(self.agent.run("wrong", session)["status"], "needs_input")
        result = self.agent.run("2", session)
        self.assertEqual(result["status"], "success", result["message"])
        self.assertEqual(extra["origin"][:2], (10, 20))
        self.assertAlmostEqual(extra["origin"][2], 1.5)
        self.assertEqual(bolt["origin"], (90, 0, 0))
        self.assertEqual(nut["origin"], (10, 20, 30))

    def test_tighten_and_loosen_nut_on_existing_bolt_screw_mate(self):
        first = self.agent.run("make a new M8 x 20 nut and bolt")
        session = first["conversation_id"]
        self.assertEqual(self.agent.run("yes", session)["status"], "success")
        bolt, nut = self.adapter.features
        # Orient the shank along assembly X so a world-Z translation would fail.
        bolt["rotation"] = nut["rotation"] = (0,1,0, 0,0,1, 1,0,0)
        nut["origin"] = (nut["origin"][2], 0, 0)
        pose = bolt["origin"], bolt["rotation"]
        start = nut["origin"]
        self.assertTrue(self.agent.run("add a screw mate", session)["data"]["created"])
        setup = self.agent.run("i want the nut slide on the bolt like we are tighting or lousing the nutbolt", session)
        self.assertEqual(setup["status"], "success", setup["message"])
        self.assertFalse(setup["data"]["created"])
        self.assertTrue(bolt["fixed"])
        self.assertFalse(nut["fixed"])
        for command, travel in (("tighten the nut", 1.25), ("loosen it", -1.25),
                                ("tighten the nut a quarter turn", .3125), ("turn nut 90 degrees counterclockwise", -.3125)):
            previous = nut["origin"][0]
            result = self.agent.run(command, session)
            self.assertEqual(result["status"], "success", result["message"])
            self.assertEqual(result["data"]["component"], nut["name"])
            self.assertAlmostEqual(previous - nut["origin"][0], travel)
            self.assertEqual(nut["origin"][1:], start[1:])
            if travel == .3125:
                self.assertAlmostEqual(nut["rotation"][1], 0)
                self.assertAlmostEqual(nut["rotation"][2], -1)
            self.assertEqual((bolt["origin"], bolt["rotation"]), pose)
        self.assertEqual(nut["origin"], start)
        self.assertEqual(self.agent.run("loosen nut 100 turns", session)["status"], "error")
        self.assertEqual(nut["origin"], start)
        self.assertEqual(self.agent.run("turn bolt a quarter turn", session)["status"], "success")
        self.assertTrue(nut["fixed"])
        self.assertFalse(bolt["fixed"])
        self.assertEqual(len([f for f in self.adapter.features if f["type"] == "Mate"]), 1)

    def test_existing_screw_switches_fixed_component_before_driving_nut(self):
        def transform(values):
            return SimpleNamespace(ArrayData=tuple(values))

        class Component:
            GetMates = ("existing screw",)

            def __init__(self, name, z, fixed):
                self.Name2, self.IsFixed = name, fixed
                self.Transform2 = transform((1,0,0, 0,1,0, 0,0,1, 0,0,z, 1,0,0,0))

            def SetTransformAndSolve2(self, pose):
                if self.IsFixed:
                    return False
                self.Transform2 = pose
                return True

        spec = {"diameter": 8, "length": 20}
        bolt, nut = Component("bolt", 0, False), Component("nut", .0185, True)
        initial_bolt = bolt.Transform2.ArrayData
        assembly = SimpleNamespace(EditRebuild3=True, GraphicsRedraw2=None, ClearSelection2=lambda _: None)
        adapter = SimpleNamespace(current_model=assembly, _math_transform=transform)
        screw = SimpleNamespace(IsSuppressed=False, GetDefinition=SimpleNamespace(RevolutionType=1, RevolutionVal=.00125))
        with patch("solidworks_mcp.com_adapter.threads._existing_screw", return_value=screw), \
             patch("solidworks_mcp.com_adapter.threads._set_fixed", side_effect=lambda _, c, fixed: setattr(c, "IsFixed", fixed)):
            self.assertFalse(add_screw_mate(adapter, bolt, nut, spec, 1.25, "nut"))
            self.assertTrue(bolt.IsFixed)
            self.assertFalse(nut.IsFixed)
            turn_fastener(adapter, bolt, nut, spec, 1.25, .25, "nut")
            self.assertAlmostEqual(nut.Transform2.ArrayData[11], .0185 - .0003125)
            self.assertAlmostEqual(nut.Transform2.ArrayData[1], -1)
            self.assertEqual(bolt.Transform2.ArrayData, initial_bolt)

    def test_move_on_wrong_document_or_blocked_by_mates(self):
        for setup in (lambda: None, self.adapter.new_part):
            setup()
            reply = self.agent.run("move bolt on the nut")
            self.assertEqual(reply["status"], "error")
            self.assertIn("Activate the assembly", reply["message"])
        bolt, nut = self.make_pair()
        self.assertTrue(self.adapter.mate_planes("Top Plane@" + bolt["name"], "Top Plane@" + nut["name"]).success)
        reply = self.agent.run("move bolt on the nut")
        self.assertEqual(reply["status"], "error")
        self.assertIn("mates", reply["message"])
        self.assertEqual(bolt["origin"], (90, 0, 0))

    def test_reuse_active_shape_and_explicit_new_document(self):
        self.adapter.new_part()
        for command, expected in (("make a block 40 x 30 x 10 on front plane", "Part1.SLDPRT"),
                                  ("make a new block 60 x 30 x 10 on front plane", "Part2.SLDPRT")):
            result = self.agent.run(command, design_tool=True)
            self.assertEqual(result["status"], "success", result["message"])
            self.assertEqual(self.adapter.active_document, expected)

    def test_com_move_restores_fixed_state_and_rolls_back_on_failed_rebuild(self):
        def matrix(values):
            return SimpleNamespace(ArrayData=tuple(values))

        class Bolt:
            Name2 = "M8x30-Bolt^Assem1-1"
            IsFixed = True
            GetMates = ()

            def Select4(self, *args):
                return True

            def SetTransformAndSolve2(self, transform):
                if self.IsFixed:
                    return False
                self.Transform2 = transform
                return True

        bolt = Bolt()
        class Assembly:
            rebuild_ok = True

            def UnfixComponent(self):
                bolt.IsFixed = False

            def FixComponent(self):
                bolt.IsFixed = True

            def EditRebuild3(self):
                return self.rebuild_ok

            def ClearSelection2(self, all_marks):
                pass

        assembly = Assembly()
        driver = SimpleNamespace(current_model=assembly, _math_transform=matrix)
        original = matrix([1,0,0, 0,1,0, 0,0,1, .1,0,0, 1,0,0,0])
        anchor = matrix([0,0,1, 0,1,0, -1,0,0, .01,.02,.03, 1,0,0,0])
        nut = SimpleNamespace(Transform2=anchor)
        bolt.Transform2 = original
        self.assertTrue(SolidWorksCOMAdapter._place_fastener(driver, bolt, nut, -28.5))
        self.assertTrue(bolt.IsFixed)
        self.assertAlmostEqual(bolt.Transform2.ArrayData[9], .0385)
        self.assertEqual(bolt.Transform2.ArrayData[:9], anchor.ArrayData[:9])
        bolt.Transform2 = original
        assembly.rebuild_ok = False
        with self.assertRaisesRegex(ValueError, "after rebuilding"):
            SolidWorksCOMAdapter._place_fastener(driver, bolt, nut, -28.5)
        self.assertIs(bolt.Transform2, original)
        self.assertTrue(bolt.IsFixed)
        self.assertIs(nut.Transform2, anchor)

    def test_pair_without_component_files_or_origins(self):
        start = self.agent.run("plan nut bolt")
        session = start["conversation_id"]
        self.assertEqual(start["missing_fields"], ["diameter"])
        size = self.agent.run("M8", session)
        self.assertEqual(size["missing_fields"], ["length"])
        invalid = self.agent.run("2", session)
        self.assertEqual(invalid["missing_fields"], ["length"])
        layout = self.agent.run("30 mm", session)
        self.assertIn("flush", layout["message"])
        with tempfile.TemporaryDirectory() as tmp:
            planned = self.agent.run("use defaults", session)
            self.assertEqual(planned["status"], "planned", planned["message"])
            self.assertFalse(self.adapter.has_active_document())
            builds = [f["arguments"]["depth"] for s in planned["plan"] if s["operation"] == "create_virtual_component"
                      for f in s["arguments"]["features"] if f["operation"] == "feature_extrude_boss"]
            self.assertEqual(builds, [5.3, 35.3, 6.8])
            built = self.agent.run("build plan", session)
            self.assertEqual(built["status"], "success", built["message"])
            inserted = [f for f in self.adapter.features if f["type"] == "Component"]
            self.assertEqual(len(inserted), 2)
            for component, internal in zip(inserted, (False, True)):
                threads = [f for f in component["features"] if f["type"] == "Thread"]
                self.assertEqual(len(threads), 1)
                self.assertEqual((threads[0]["internal"], threads[0]["pitch"]), (internal, 1.25))
            self.assertTrue(all(f["virtual"] for f in inserted))
            self.assertFalse(self.adapter._saved_components)
            self.assertEqual(inserted[0]["origin"], (0,0,0))
            self.assertAlmostEqual(inserted[1]["origin"][2] + 6.8, 35.3)
            self.assertEqual(list(Path(tmp).iterdir()), [])
            repeat = self.agent.run("make a new M8 x 30 bolt and nut")
            again = self.agent.run(tmp, repeat["conversation_id"])
            self.assertIn("M8x30-Assembly.SLDASM", again["message"])

    def test_edit_threads_on_existing_pair_and_retry(self):
        self.adapter.new_assembly()
        for name in ("Bolt", "Nut"):
            self.adapter.features.append(dict(type="Component", name=f"M8x30-{name}^Assem2-1", features=[]))
        document = self.adapter.active_document
        for command in ("add threads to the nut and bolt", "thread both"):
            reply = self.agent.run(command)
            self.assertEqual(reply["status"], "success", reply["message"])
            self.assertEqual([op["tool"] for op in reply["operations"]], ["thread_fasteners"])
            self.assertEqual(self.adapter.active_document, document)
        self.assertEqual([len(c["features"]) for c in self.adapter.features], [1, 1])

    def test_reported_pending_generic_prompt_accepts_fastener_designation(self):
        self.agent.pending["old"] = Plan([Step("custom_design", {
            "brief": "nut bolt", "scope": "assembly", "components": ["nut", "bolt"], "placements": []
        })], True)
        result = self.agent.run("M8 x 30", "old")
        self.assertEqual(result["missing_fields"], ["layout_and_folder"])
        self.assertNotIn("origin", result["message"])

    def test_structured_size_is_kept(self):
        start = self.agent.run("nut bolt", separate=True, dimensions={"bolt_length": 30})
        self.assertEqual(start["missing_fields"], ["diameter"])
        reply = self.agent.run("M8", start["conversation_id"])
        self.assertIn("M8 x 30 mm", reply["message"])

    def test_generic_assembly_can_accept_file_and_position_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "part.SLDPRT")
            path.touch()
            session = self.agent.run("plan a test assembly")["conversation_id"]
            self.agent.run("base, top", session)
            first = self.agent.run(f'"{path}"', session)
            self.assertIn("Where should I place base?", first["message"])
            self.assertIn("top", self.agent.run("origin", session)["message"])
            self.agent.run(f'"{path}"', session)
            self.agent.run("(10,20,30)", session)
            plan = self.agent.run("placement only", session)
            positions = [s["arguments"] for s in plan["plan"] if s["operation"] == "insert_component"]
            self.assertEqual([(p["x"],p["y"],p["z"]) for p in positions], [(0,0,0),(10,20,30)])
