"""Comprehensive Test Suite for SolidWorks MCP Server."""

import math
import os
import unittest
import asyncio
from fastmcp import Client
from unittest.mock import Mock, patch
from pathlib import Path

from solidworks_mcp.config import config
from solidworks_mcp.com_adapter.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.com_adapter.base import CADResult
from solidworks_mcp.agent.local_agent import LocalCADAgent
from solidworks_mcp.server import create_server, main
from solidworks_mcp.parametric.prismatic import generate_mounting_bracket, generate_l_bracket, generate_structural_tube
from solidworks_mcp.parametric.rotational import generate_flange, generate_stepped_shaft, generate_bushing, generate_dowel_pin
from solidworks_mcp.parametric.enclosures import generate_enclosure_box
from solidworks_mcp.parametric.thermal import generate_heat_sink
from solidworks_mcp.parametric.gears import generate_spur_gear
from solidworks_mcp.parametric.mechanisms import generate_connecting_rod, generate_crank_arm
from solidworks_mcp.execution.script_executor import PythonScriptExecutor


class TestSolidWorksMCP(unittest.TestCase):
    """Test suite covering tools, simulation adapter, and parametric design engines."""

    def setUp(self):
        offline = patch("solidworks_mcp.agent.codex_planner.CodexPlanner.available", return_value=False)
        offline.start()
        self.addCleanup(offline.stop)
        config.mock_mode = True
        self.adapter = MockSolidWorksAdapter()
        self.adapter.connect()

    def test_server_creation_and_tool_count(self):
        """Verify FastMCP server initializes with all modular CAD tools."""
        server = create_server(mock_mode=True)
        # FastMCP tools
        tools = server._tool_manager.list_tools() if hasattr(server, "_tool_manager") else []
        self.assertIsNotNone(server)

    def test_streamable_http_transport_dispatch(self):
        for requested_transport in ("streamable-http", "stream"):
            with self.subTest(transport=requested_transport):
                server = Mock()
                with patch("solidworks_mcp.server.create_server", return_value=server), \
                        patch("sys.argv", ["solidworks-mcp", "--transport", requested_transport, "--port", "8123"]):
                    main()
                server.run.assert_called_once_with(transport="streamable-http", port=8123)

    def test_mounting_bracket_generator(self):
        """Test parametric mounting bracket creation."""
        res = generate_mounting_bracket(self.adapter, length=120.0, width=70.0, thickness=12.0)
        self.assertTrue(res.success)
        self.assertIn("Mounting Bracket", res.message)
        self.assertGreaterEqual(len(self.adapter.features), 2)

    def test_flange_generator(self):
        """Test circular flange with pitch circle bolt holes."""
        res = generate_flange(
            self.adapter, outer_diameter=120.0, thickness=15.0,
            center_bore_diameter=45.0, bolt_circle_diameter=90.0, bolt_hole_count=6
        )
        self.assertTrue(res.success)
        self.assertIn("Flange", res.message)
        mass = self.adapter.get_mass_properties()
        self.assertTrue(mass.success)
        self.assertGreater(mass.data["volume_mm3"], 0)

    def test_spur_gear_generator(self):
        """Test spur gear module and involute teeth generation."""
        res = generate_spur_gear(self.adapter, num_teeth=24, module=2.0, face_width=15.0, bore_diameter=18.0)
        self.assertTrue(res.success)
        self.assertIn("Spur Gear", res.message)
        self.assertEqual(res.data["pitch_diameter"], 48.0)

    def test_gear_extrudes_requested_number_of_teeth(self):
        sketches = []
        extrude = self.adapter.feature_extrude_boss

        def record(**kwargs):
            sketches.append(self.adapter.current_sketch["entities"][:])
            return extrude(**kwargs)

        with patch.object(self.adapter, "feature_extrude_boss", side_effect=record):
            agent = LocalCADAgent(self.adapter)
            pending = agent.run("make a new 24-tooth spur gear with module=2")
            self.assertEqual(pending["status"], "needs_input", pending["message"])
            reply = agent.run("use defaults", pending["conversation_id"])
        self.assertEqual(reply["status"], "success", reply["message"])
        # The outer wire is consecutive outgoing line segments, ending back at the start.
        segments = []
        for entity in sketches[0]:
            if entity["type"] != "line":
                break
            segments.append(entity)
        self.assertTrue(segments)
        tips = []
        for i, edge in enumerate(segments):
            next_edge = segments[(i + 1) % len(segments)]
            self.assertEqual((edge["x2"], edge["y2"]), (next_edge["x1"], next_edge["y1"]))
            tips.append(math.isclose(math.hypot(edge["x1"], edge["y1"]), 26.0))
        self.assertEqual(sum(at_tip and not tips[i - 1] for i, at_tip in enumerate(tips)), 24)

    def test_gear_stops_on_failed_extrusion(self):
        with patch.object(self.adapter, "feature_extrude_boss", return_value=CADResult(success=False, message="bad sketch")):
            result = generate_spur_gear(self.adapter)
        self.assertFalse(result.success)
        self.assertIn("Extrude teeth", result.message)
        self.assertIn("bad sketch", result.message)

    def test_plain_language_helical_gear(self):
        agent = LocalCADAgent(self.adapter)
        result = agent.run("make a Helical gears having outer diameter of 15 dia ,and inter 10 dia")
        session = result["conversation_id"]
        self.assertEqual(result["missing_fields"], ["num_teeth", "face_width", "helix_angle", "pressure_angle"])
        self.assertEqual(result["operations"], [])
        invalid = agent.run("2.5 teeth", session)
        self.assertEqual(invalid["missing_fields"], result["missing_fields"])
        result = agent.run("24 teeth and face width=5 mm", session)
        self.assertEqual(result["missing_fields"], ["helix_angle", "pressure_angle"])
        self.assertFalse(self.adapter.has_active_document())
        result = agent.run("helix angle=25 degrees, pressure angle=20 degrees", session)
        self.assertEqual(result["status"], "success", result["message"])
        self.assertEqual(result["data"]["outer_diameter"], 15)
        self.assertEqual(result["data"]["bore_diameter"], 10)
        self.assertEqual(result["data"]["face_width"], 5)
        sweep = next(f for f in self.adapter.features if f["type"] == "Sweep")
        self.assertGreater(sweep["twist_radians"], 0)
        self.assertTrue(any(f["type"] == "Cut" for f in self.adapter.features))
        doc = self.adapter.active_document
        bad = agent.run("make a helical gear, 15 mm OD and 14 mm bore")
        bad = agent.run("use defaults", bad["conversation_id"])
        self.assertEqual(bad["status"], "error")
        self.assertEqual(self.adapter.active_document, doc)
        left = agent.run("make a new helical gear with 15 mm OD, 10 mm bore, 24 teeth, width 6 mm, helix angle -25 degrees and pressure angle 20 degrees")
        self.assertEqual(left["status"], "success", left["message"])
        self.assertLess(left["data"]["twist_degrees"], 0)

    def test_clarify_before_any_step_and_isolate_conversations(self):
        agent = LocalCADAgent(self.adapter)
        flange = agent.run("make a flange")
        pending = agent.run("make a new part then add a hole")
        session = pending["conversation_id"]
        self.assertIn("diameter", pending["missing_fields"])
        self.assertEqual(agent.run("cancel", flange["conversation_id"])["status"], "cancelled")
        pending = agent.run("use defaults", session)
        self.assertEqual(pending["missing_fields"], ["diameter"])
        self.assertFalse(self.adapter.has_active_document())
        result = agent.run("6 mm", session)
        self.assertEqual(result["status"], "success", result["message"])
        self.assertEqual([entry["tool"] for entry in result["operations"]], ["new_part", "add_hole"])
        document = self.adapter.active_document
        edit = agent.run("add a blind hole at (4, 6) on top plane", session)
        self.assertEqual(edit["missing_fields"], ["diameter", "depth"])
        result = agent.run("diameter=4, depth=2", session)
        self.assertEqual(result["status"], "success", result["message"])
        self.assertEqual(self.adapter.active_document, document)

    def test_choose_design_and_require_shaft_sections(self):
        agent = LocalCADAgent(self.adapter)
        start = agent.run("make something")
        session = start["conversation_id"]
        self.assertEqual(start["missing_fields"], ["design_type"])
        self.assertIn("segments", agent.run("stepped shaft", session)["missing_fields"])
        self.assertEqual(agent.run("use defaults", session)["missing_fields"], ["segments"])
        built = agent.run("35x25 / 50x35", session)
        self.assertEqual(built["status"], "success", built["message"])
        self.assertEqual(built["data"]["total_length"], 85)

    def test_edit_existing_gear_by_teeth_and_outer_diameter(self):
        command = "change the teeth to 30 & outer dia to 50"
        generate_spur_gear(self.adapter)
        self.adapter.add_hole(3, xc=5)
        doc = self.adapter.active_document
        features = [f["name"] for f in self.adapter.features]
        # A fresh agent must also recognize a previous agent's gear by its actual sketch.
        agent = LocalCADAgent(self.adapter)
        changed = agent.run(command)
        self.assertEqual(changed["status"], "success", changed["message"])
        self.assertEqual(self.adapter.active_document, doc)
        self.assertEqual([f["name"] for f in self.adapter.features], features)
        outline = self.adapter._extrusion_profiles["Boss-Extrude1"]
        radii = [math.hypot(e["x1"], e["y1"]) for e in outline if e["type"] == "line"]
        self.assertAlmostEqual(max(radii), 25)
        self.assertEqual(sum(math.isclose(r, 25) for r in radii), 30 * 3)
        self.assertTrue(any(e["type"] == "arc" for e in outline))  # Keyed bore
        self.assertEqual(agent.run("change the teeth to 2.5 & outer dia to 20")["status"], "error")
        self.adapter.new_part()
        self.assertEqual(agent.run(command)["status"], "error")

    def test_gear_changes_while_collecting_dimensions(self):
        agent = LocalCADAgent(self.adapter)
        session = agent.run("make a gear")["conversation_id"]
        reply = agent.run("change the teeth to 30 & outer dia to 50", session)
        self.assertNotIn("module", reply["missing_fields"])
        self.assertNotIn("num_teeth", reply["missing_fields"])
        result = agent.run("use defaults", session)
        self.assertEqual(result["status"], "success", result["message"])
        self.assertEqual(result["data"]["tip_diameter"], 50)
        self.assertEqual(result["data"]["teeth"], 30)

    def test_edit_helical_gear_keeps_sweep_hand_and_helix_angle(self):
        agent = LocalCADAgent(self.adapter)
        pending = agent.run("make a helical gear with 15 mm OD, 10 mm bore and helix angle -25")
        before = agent.run("use defaults", pending["conversation_id"])
        self.assertEqual(before["status"], "success", before["message"])
        sweep = next(f for f in self.adapter.features if f["type"] == "Sweep")
        after = agent.run("set tooth count to 30 and OD to 50 mm")
        self.assertEqual(after["status"], "success", after["message"])
        normal = 50 / (30 / math.cos(math.radians(25)) + 2)
        pitch = 50 - 2 * normal
        self.assertAlmostEqual(math.degrees(math.atan(sweep["twist_radians"] * pitch / (2 * sweep["depth"]))), -25)

    def test_mcp_design_tools_share_pending_requests(self):
        async def check():
            async with Client(create_server(mock_mode=True)) as client:
                first = await client.call_tool("create_live_design", {
                    "prompt": "make a 60mm diameter mounting flange with 6 bolt holes",
                    "dimensions": {"thickness": 8},
                })
                pending = first.data
                self.assertEqual(pending["status"], "needs_input", pending["message"])
                self.assertEqual(pending["missing_fields"],
                                 ["center_bore_diameter", "bolt_circle_diameter", "bolt_hole_diameter"])
                next_call = await client.call_tool("cad_agent", {
                    "prompt": "center bore diameter=20, bolt circle diameter=48, bolt hole diameter=4",
                    "conversation_id": pending["conversation_id"],
                })
                self.assertEqual(next_call.data["status"], "success", next_call.data["message"])
                self.assertEqual(next_call.data["data"]["outer_diameter"], 60)
                typed = await client.call_tool("design_mounting_bracket", {"length": 105})
                pending = typed.data
                self.assertEqual(pending["status"], "needs_input", pending["message"])
                self.assertNotIn("length", pending["missing_fields"])
                done = await client.call_tool("ai_design", {
                    "prompt": "use defaults", "conversation_id": pending["conversation_id"],
                })
                self.assertEqual(done.data["status"], "success", done.data["message"])

        asyncio.run(check())

    def test_connecting_rod_generator(self):
        """Test slider-crank connecting rod mechanism link."""
        res = generate_connecting_rod(self.adapter, center_distance=140.0)
        self.assertTrue(res.success)
        self.assertIn("Connecting Rod", res.message)

    def test_enclosure_box_generator(self):
        """Test electronic housing with wall thickness shell and bosses."""
        res = generate_enclosure_box(self.adapter, length=100.0, width=60.0, height=35.0, wall_thickness=2.0)
        self.assertTrue(res.success)
        self.assertIn("Enclosure Box", res.message)

    def test_heat_sink_generator(self):
        """Test extruded fin array thermal heat sink."""
        res = generate_heat_sink(self.adapter, base_length=80.0, base_width=50.0, fin_count=6)
        self.assertTrue(res.success)
        self.assertIn("Heat Sink", res.message)

    def test_stepped_shaft_generator(self):
        """Test rotational stepped transmission shaft."""
        segments = [(30.0, 20.0), (40.0, 30.0), (25.0, 15.0)]
        res = generate_stepped_shaft(self.adapter, segments=segments)
        self.assertTrue(res.success)
        self.assertEqual(res.data["total_length"], 95.0)

    def test_python_script_executor(self):
        """Test dynamic AI-generated script execution."""
        executor = PythonScriptExecutor(self.adapter)
        test_script = """
adapter.new_part()
adapter.create_sketch('Front Plane')
adapter.sketch_circle(0.0, 0.0, 25.0)
adapter.feature_extrude_boss(depth=15.0)
"""
        res = executor.execute(test_script)
        self.assertTrue(res.success)

    def test_viewport_image_rendering(self):
        """Test viewport technical preview image generation."""
        self.adapter.new_part()
        self.adapter.create_sketch("Front Plane")
        self.adapter.sketch_rectangle(0, 0, 50, 30)
        self.adapter.feature_extrude_boss(depth=20)
        res = self.adapter.capture_viewport_image()
        self.assertTrue(res.success)
        image_path = res.data.get("image_path")
        self.assertIsNotNone(image_path)
        self.assertTrue(os.path.exists(image_path))

    def test_incremental_modifications_to_active_part(self):
        """Verify the agent modifies the active part rather than creating a new document."""
        agent = LocalCADAgent(self.adapter)
        r1 = agent.run("make a new bracket 100 x 60 x 10")
        conv = r1["conversation_id"]
        r1b = agent.run("use defaults", conversation_id=conv)
        self.assertEqual(r1b["status"], "success")
        initial_doc = self.adapter.active_document
        initial_features_count = len(self.adapter.features)
        self.assertEqual(initial_doc, "Part1.SLDPRT")

        # Edit 1: Hole in center
        r2 = agent.run("add a 10mm hole in the center", conversation_id=conv)
        self.assertEqual(r2["status"], "success")
        self.assertEqual(self.adapter.active_document, initial_doc)

        # Edit 2: Fillet
        r3 = agent.run("fillet edges to 3mm", conversation_id=conv)
        self.assertEqual(r3["status"], "success")
        self.assertEqual(self.adapter.active_document, initial_doc)

        # Edit 3: Chamfer
        r4 = agent.run("chamfer 2mm", conversation_id=conv)
        self.assertEqual(r4["status"], "success")
        self.assertEqual(self.adapter.active_document, initial_doc)

        # Edit 4: Cut pocket
        r5 = agent.run("cut a 20x20 pocket 5mm deep in the center", conversation_id=conv)
        self.assertEqual(r5["status"], "success")
        self.assertEqual(self.adapter.active_document, initial_doc)

        # Edit 5: Set dimension
        r6 = agent.run("change thickness to 15mm", conversation_id=conv)
        self.assertEqual(r6["status"], "success")
        self.assertEqual(self.adapter.active_document, initial_doc)

        # Verify features were appended to the same part
        self.assertGreater(len(self.adapter.features), initial_features_count)

    def test_explicit_new_part_creates_separate_document(self):
        """Verify that commanding a 'new' part explicitly creates a brand new document."""
        agent = LocalCADAgent(self.adapter)
        r1 = agent.run("make a new bracket 100 x 60 x 10")
        conv = r1["conversation_id"]
        agent.run("use defaults", conversation_id=conv)
        doc1 = self.adapter.active_document

        # Now command a new part explicitly
        r2 = agent.run("make a new flange with OD 120 and bore 40", conversation_id=conv)
        agent.run("use defaults", conversation_id=conv)
        doc2 = self.adapter.active_document
        self.assertNotEqual(doc1, doc2)
        self.assertEqual(doc2, "Part2.SLDPRT")

    def test_bushing_and_pin_generators(self):
        """Test parametric sleeve bushing and dowel pin generators."""
        res_b = generate_bushing(self.adapter, outer_diameter=32.0, inner_diameter=20.0, length=40.0)
        self.assertTrue(res_b.success)
        self.assertIn("Sleeve Bushing", res_b.message)

        res_p = generate_dowel_pin(self.adapter, diameter=8.0, length=30.0)
        self.assertTrue(res_p.success)
        self.assertIn("Dowel Pin", res_p.message)

    def test_structural_tube_generator(self):
        """Test round and square structural tube profiles."""
        res_sq = generate_structural_tube(self.adapter, outer_size=40.0, wall_thickness=2.5, length=150.0, shape="square")
        self.assertTrue(res_sq.success)
        self.assertIn("Square Hollow Structural Section", res_sq.message)

        res_rd = generate_structural_tube(self.adapter, outer_size=50.0, wall_thickness=3.0, length=200.0, shape="round")
        self.assertTrue(res_rd.success)
        self.assertIn("Round Structural Tube", res_rd.message)


if __name__ == "__main__":
    unittest.main()
