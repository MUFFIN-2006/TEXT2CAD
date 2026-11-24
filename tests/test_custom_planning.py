import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from fastmcp import Client

from solidworks_mcp.agent.local_agent import LocalCADAgent
from solidworks_mcp.com_adapter.base import BaseSolidWorksAdapter, CADResult
from solidworks_mcp.com_adapter.solidworks_com import PYWIN32_AVAILABLE, SolidWorksCOMAdapter
from solidworks_mcp.server import create_server


class CustomPlanningTests(unittest.TestCase):
    def setUp(self):
        offline = patch("solidworks_mcp.agent.codex_planner.CodexPlanner.available", return_value=False)
        offline.start()
        self.addCleanup(offline.stop)
        self.adapter = Mock(spec=BaseSolidWorksAdapter)
        self.adapter.component_file_exists.side_effect = lambda path: Path(path).is_file()
        self.agent = LocalCADAgent(self.adapter)

    def test_custom_part_with_an_arbitrary_closed_profile(self):
        result = self.agent.run("plan a guide shoe")
        session = result["conversation_id"]
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("guide shoe", result["message"])
        result = self.agent.run("part", session)
        self.assertEqual(result["status"], "needs_input")
        result = self.agent.run("extrude profile (0,0) (50,0) (40,15) (0,12) by 8 on right plane then add a hole", session)
        self.assertEqual(["diameter"], result["missing_fields"])
        result = self.agent.run("6 mm", session)
        self.assertEqual(result["status"], "planned", result["message"])
        self.assertEqual([s["operation"] for s in result["plan"]],
                         ["new_part", "create_sketch", "sketch_closed_polyline", "feature_extrude_boss", "add_hole"])
        self.assertEqual(result["plan"][1]["arguments"]["plane_or_face"], "Right Plane")
        self.assertEqual(result["plan"][-1]["arguments"], dict(diameter=6, through_all=True, flip_dir=True,
                                                                plane_or_face="Right Plane", xc=25, yc=7.5))
        self.assertEqual(result["operations"], [])
        self.adapter.connect.assert_not_called()

    def test_trapezoidal_plate_without_vertices(self):
        result = self.agent.run("plan a new trapezoidal plate 50 mm bottom, 40 mm top, 20 mm tall "
                                "and 8 mm thick, left edge vertical then add a hole")
        self.assertEqual(result.get("missing_fields"), ["diameter"], result["message"])
        plan = self.agent.run("6 mm", result["conversation_id"])["plan"]
        self.assertEqual(plan[2]["arguments"]["points"], [(0, 0), (50, 0), (40, 20), (0, 20)])
        self.assertEqual((plan[-1]["arguments"]["xc"], plan[-1]["arguments"]["yc"]), (25, 10))

    def test_feature_avoids_concavity_and_existing_hole(self):
        profile = "plan extrude profile (0,0) (30,0) (30,10) (10,10) (10,30) (0,30) by 5 on top plane"
        plan = self.agent.run(profile + " then add a 4 mm hole at (5,5) then add a 4 mm hole")["plan"]
        first, second = [step["arguments"] for step in plan[-2:]]
        self.assertEqual((first["xc"], first["yc"]), (5, 5))
        x, y = second["xc"], second["yc"]
        self.assertTrue(2 < x < 8 or 2 < y < 8)
        self.assertGreater((x-5)**2 + (y-5)**2, 4**2)
        oversized = self.agent.run(profile + " then add a 30 mm hole")
        self.assertEqual(oversized["status"], "error")
        self.assertEqual(oversized["operations"], [])

    def test_follow_up_uses_current_part_outline(self):
        from solidworks_mcp.com_adapter.mock_adapter import MockSolidWorksAdapter
        adapter = MockSolidWorksAdapter()
        agent = LocalCADAgent(adapter)
        base = agent.run("extrude profile (20,20) (70,20) (60,40) (20,40) by 8 on top plane")
        self.assertEqual(base["status"], "success", base["message"])
        session = base["conversation_id"]
        hole = agent.run("plan add a 6 mm hole", session)["plan"][-1]["arguments"]
        self.assertEqual((hole["xc"], hole["yc"], hole["plane_or_face"]), (45, 30, "Top Plane"))
        adapter.new_part()
        stale = agent.run("build plan", session)
        self.assertEqual(stale["status"], "error")
        self.assertEqual(stale["operations"], [])

    def test_machine_collects_parts_before_compiling_assembly(self):
        with TemporaryDirectory() as folder:
            frame = Path(folder, "frame.SLDPRT")
            drive = Path(folder, "drive.SLDASM")
            drive.touch()  # Empty fixture for path validation only.
            pending = self.agent.run("plan a transfer machine")
            session = pending["conversation_id"]
            for answer in ("assembly", "frame, drive"):
                self.assertEqual(self.agent.run(answer, session)["status"], "needs_input")
            reply = self.agent.run(f'block 250 x 100 x 10 on top plane then save as "{frame}" at (0,0,0)', session)
            self.assertIn("drive", reply["message"])
            reply = self.agent.run(f'"{drive}" at (45,0,0)', session)
            self.assertIn("constrained", reply["message"])
            reply = self.agent.run('mate "Top Plane@frame-1" to "Top Plane@drive-1"', session)
            self.assertEqual(reply["status"], "planned", reply["message"])
            commands = [s["operation"] for s in reply["plan"]]
            self.assertEqual(commands, ["new_part", "create_sketch", "sketch_rectangle", "feature_extrude_boss",
                                        "save_model", "new_assembly", "insert_component", "insert_component", "mate_planes"])
            self.assertEqual(reply["plan"][-2]["arguments"]["x"], 45)
            self.assertFalse(frame.exists())
            self.adapter.connect.assert_not_called()
            # Verify explicit execution dispatch without creating documents or geometry.
            for method in set(commands + ["connect"]):
                getattr(self.adapter, method).return_value = CADResult(success=True, message="Recorded")
            self.adapter.has_active_document.return_value = True
            built = self.agent.run("build plan", session)
            self.assertEqual(built["status"], "success", built["message"])
            self.assertEqual(self.adapter.insert_component.call_count, 2)
            self.assertEqual(self.agent.run("build plan", session)["status"], "error")

    def test_mcp_custom_design_and_plan_cancellation(self):
        async def check():
            async with Client(create_server(mock_mode=True)) as client:
                start = (await client.call_tool("create_live_design", {"prompt": "plan a test fixture"})).data
                self.assertEqual(start["status"], "needs_input")
                session = start["conversation_id"]
                result = (await client.call_tool("ai_design", {"prompt": "block 40 x 30 x 10 on front plane",
                                                               "conversation_id": session})).data
                self.assertEqual(result["status"], "planned", result["message"])
                self.assertNotIn("preview_image", result)
                await client.call_tool("cad_agent", {"prompt": "cancel", "conversation_id": session})
                result = (await client.call_tool("cad_agent", {"prompt": "build plan", "conversation_id": session})).data
                self.assertEqual(result["status"], "error")

        asyncio.run(check())

    def test_missing_component_can_be_corrected_in_place(self):
        with TemporaryDirectory() as folder:
            pending = self.agent.run("design a conveyor, dont start making anything now")
            session = pending["conversation_id"]
            self.agent.run("assembly", session)
            self.agent.run("drive", session)
            path = Path(folder, "drive.SLDASM")
            answer = f'"{path}" at (0,0,0)'
            reply = self.agent.run(answer, session)
            self.assertIn("not found", reply["message"])
            path.touch()
            self.agent.run(answer, session)
            reply = self.agent.run("placement only", session)
            self.assertEqual(reply["status"], "planned", reply["message"])
            self.assertEqual([s["operation"] for s in reply["plan"]], ["new_assembly", "insert_component"])
            self.adapter.connect.assert_not_called()

    @unittest.skipUnless(PYWIN32_AVAILABLE, "Windows COM argument marshaling")
    def test_native_assembly_arguments_without_a_solidworks_session(self):
        # Only build COM argument arrays; the application and document are stand-ins.
        bridge = object.__new__(SolidWorksCOMAdapter)
        model = Mock()
        bridge.swApp = SimpleNamespace(ActiveDoc=model)
        model.GetType = 2
        model.AddComponents3.return_value = [SimpleNamespace(Name2="Drive-1")]
        with TemporaryDirectory() as folder:
            path = Path(folder, "drive.SLDASM")
            path.touch()
            result = bridge.insert_component(str(path), 50, -10, 125)
            self.assertTrue(result.success, result.message)
            paths, transforms, systems = model.AddComponents3.call_args.args
            self.assertEqual(list(paths.value), [str(path)])
            self.assertEqual(list(transforms.value)[9:13], [0.05, -0.01, 0.125, 1])
            self.assertEqual(list(systems.value), [""])
        model.GetComponentByName.side_effect = lambda name: SimpleNamespace(GetSelectByIDString=name + "@Test")
        def add_mate(*args):
            args[-1].value = 1
            return object()
        model.AddMate5.side_effect = add_mate
        result = bridge.mate_planes("Front Plane@Frame-1", "Top Plane@Drive-1")
        self.assertTrue(result.success, result.message)
        selections = [call.args[0] for call in model.Extension.SelectByID2.call_args_list]
        self.assertEqual(selections, ["Front Plane@Frame-1@Test", "Top Plane@Drive-1@Test"])
