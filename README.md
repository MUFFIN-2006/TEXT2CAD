## TEXT2CAD
SolidWorks CAD Agent(on going)

Use the SolidWorks tools directly in a Codex chat, or open the Windows CAD terminal. Both can plan designs with Codex and execute checked operations in SolidWorks.

## Use Codex

In a new Codex chat with the `solidworks-cad` MCP server enabled, describe the part or edit you want. For example, ask Codex to plan a plate with a centered hole. The chat handles planning and can call the SolidWorks tools directly. The configured server uses `SOLIDWORKS_PLANNER=host` to avoid launching a second planner.

In the CAD terminal, type `codex plan a new rectangular solid 80 mm long, 40 mm wide and 12 mm thick`. Review the result and type `build plan` in the same terminal to apply it. Free-form planning sends the design conversation and relevant catalog excerpts to Codex using your sign-in and internet connection. Explicit CAD commands and catalog searches can run locally. Type `model status` to check which planner is configured.

## Run the agent

### ANSI and ASME dimensional references

Codex can read the installed SOLIDWORKS Toolbox ANSI Inch and ANSI Metric measurement sheets through `lookup_standard_dimensions`. It checks standard components individually during design. The source table, native length unit, part family and available options accompany each result. Specify a family ID and exact field filters to retrieve a size or thread variant. Related option tables provide values such as available bolt lengths and thread lengths. Lengths in inches convert to CAD millimetres by multiplying by 25.4. Thread counts, angles, and ratios retain their own units.

```text
find standard M8 regular flat washer
standard sheet AI_TYPE_BS:15 size=1/4, pitch=20
standard sheet AI_TYPE_BS:15 option=Length, size=1/4, length=1
plan a new ANSI M8 regular flat washer
```

Once the family and size are known, the agent uses the matching reference dimensions. Give a custom measurement whenever you need one. For example, `plan a new M8 regular flat washer with a thickness of 3 mm` uses the sheet for both diameters. You can also start with `plan a new metric regular flat washer` and reply `M8, 3 mm thick` when it asks for the size. The plan lists your changes alongside the original sheet values.

The agent reads `offline-standards/toolbox.sqlite` when present and falls back to the installed Toolbox database. Set `SOLIDWORKS_TOOLBOX_DB` to override either location. Toolbox values are modeling dimensions and can be customized. For a tolerance or specified edition, check the applicable published sheet. [ASME standards](https://www.asme.org/codes-standards/find-codes-standards) · [ANSI Webstore](https://webstore.ansi.org/)

### Offline measurement library

Type `roller chain` to find matching files and guide pages. Type `make a roller chain` to start a design. When the agent is waiting for a design answer, you can type `look up roller chain` and then return to the question. Use `offline standards` to list the library or `find standard [DIN] hex nut` to search DIN Toolbox families. The MCP tools expose the same searches through `offline_standards` and the `library` argument of `lookup_standard_dimensions`. Check the table headings and units on the referenced page when using its values.

The local snapshot contains the entire installed Toolbox database. The manufacturer guides have a local text index. The agent lists user-supplied PDFs and spreadsheets by filename from the configured reference folder. The environment variable `SOLIDWORKS_STANDARDS_FOLDER` overrides that folder.

To refresh the snapshot and index after a Toolbox update, run `.\.venv\Scripts\python.exe -m solidworks_mcp.agent.offline_standards`. Add `--download-public` to fetch missing public guides, or `--licensed-folder "C:\CAD\Standards"` to register a document folder. On a fresh installation the optional `standards-index` dependency provides the PDF reader for indexing. Table lookup and page search run locally without signing in. Free-form Codex planning still uses the internet.

Codex consults the local `Desktop/mechanical parts library.md` catalog for relevant part families, variants and standard designations. Try `find part DIN 6888` to look up a Woodruff key, or `plan a Woodruff key for my shaft` to discuss the design. The catalog is read on request, so edits take effect immediately. Set `SOLIDWORKS_PARTS_LIBRARY` to use a different file path.

From this project folder, double-click `interactive_designer.bat`. For live modeling, install SolidWorks and the project dependencies in `.venv`. From a new checkout, use `py -3.12 -m venv .venv` and `.\.venv\Scripts\python.exe -m pip install -e .`. Set `SOLIDWORKS_MOCK_MODE=1` to use the simulator. The terminal displays whether it is using live SolidWorks or simulation.

Enter one command per line, or join steps with `then`. The agent checks every step for missing design details before it changes the model. Answer in the same terminal. You can give the first value it asks for, or answer several questions with named values.

```text
make a new bracket 100 x 60 x 10
add a 6 mm hole at (20, 10)
repeat at (-20, 10)
show features
make a new flange with outer diameter=80, thickness=12 and 6 bolt holes
make a helical gear having outer diameter of 15 dia and inter 10 dia
```

For the helical gear example, the agent remembers the 15 mm outer diameter and 10 mm bore and asks for tooth count, face width, helix angle and normal pressure angle. Try answering:

```text
24 teeth, face width=5 mm, helix angle=25 degrees, pressure angle=20 degrees
```

You can also type `use defaults` to accept the values shown in the question. If a required dimension has no suggested value, the agent still asks for it. Type `cancel` to discard a pending request. For an external helical gear, `OD` means tooth-tip diameter and `inner`, `inter`, `ID` or `bore` means the central hole.

To resize a spur or helical gear made by the agent, activate its part and enter `change the teeth to 30 & outer dia to 50`. This edits the gear's existing tooth sketch. For a spur gear, those values give a module of 1.5625 mm. You can also give this command while the agent is collecting the original gear dimensions.

Lengths are in millimetres. The agent edits the active part. Use `new` for a separate part. Type `help` for more command examples or `exit` to quit. This is a command-based agent with a supported vocabulary. If it cannot parse a request, it returns guidance. For a multi-step request, it stops on the first execution error and returns the operations already performed.

In an assembly containing the agent's metric nut and bolt, type `move bolt on the nut`. The nut stays in place while the bolt lines up with its bore, with the tip flush with the outer face. Use `move nut onto the bolt` to hold the bolt in place instead. If several matching instances exist, choose one by name or list number. The agent reports when the pair is already seated or when an assembly mate controls the move.

To couple rotation and travel, say `it should rotate on the nut's thread`. The agent adds a native screw mate using the pair's coarse thread pitch. Use `turn bolt a quarter turn` to advance or `turn bolt 90 degrees counterclockwise` to back out. Clockwise is viewed from the bolt head. An M8 bolt advances 0.3125 mm per quarter turn.

To hold the bolt still, say `tighten the nut` or `loosen the nut`. Each command turns the nut one revolution unless you give an amount, such as `tighten the nut half a turn` or `loosen the nut 90 degrees`. Viewed from the bolt tip, clockwise tightening moves the nut toward the head. On the agent's coarse M8 pair, one turn moves the nut 1.25 mm. The command reuses the existing screw mate when switching which component moves.

## Custom parts and machine assemblies

For a metric hex nut and bolt, enter `make a nut and bolt` and answer the size question with, for example, `M8 x 30`. The 30 mm is measured under the bolt head. Reply `yes` to build the bolt with an external right-hand thread and the nut with a matching internal thread. M8 uses a 1.25 mm coarse pitch. Both editable components stay inside the unsaved assembly. To update a smooth pair made by an earlier version, activate its assembly and enter `add threads to the nut and bolt`. You can also specify just the nut or bolt. Native threading uses the installed SOLIDWORKS Metric Tap and Metric Die profiles. The hex dimensions use [ISO 4017 head dimensions](https://www.fastenal.com/content/product_specifications/M.HCS.4017.10.9.Z.05.pdf) and [ISO 4032 nut dimensions](https://www.fastenal.com/content/product_specifications/M.FHN.4032.10.9.YZ.01.pdf).

Type `plan a transfer machine` to discuss the machine without connecting to SolidWorks. Describe each component's geometry, dimensions and placement. In the guided assembly workflow you can also provide existing component paths or request separate output files. Use `build plan` in the same conversation to execute reviewed steps.

Describe a custom outline using lengths and relationships. Codex can derive the sketch points. For example:

## Features

- **Autonomous "Prompt-to-CAD" Live Engine**:
  - `create_live_design`: Interprets commands like *"Make a 60mm diameter mounting flange with 6 bolt holes"* or *"Design a spur gear with 24 teeth"* and builds complete parametric CAD models.
  - `modify_live_design`: Modifies or adds features (holes, cuts, pockets, bosses, fillets, chamfers, shells, dimension updates) to the active SolidWorks part document without creating a new document.
- **Intelligent Incremental Modifications (Active Part Preservation)**:
  - When a part is active in SolidWorks, follow-up commands (e.g. *"add a 10mm hole in the center"*, *"fillet edges to 3mm"*, *"cut a 20x20 pocket 5mm deep"*, *"change thickness to 15mm"*) are applied directly to that same part.
  - Brand new part documents are created only when explicitly commanded (e.g. *"make a new flange"*, *"new part"*, *"start fresh"*), or when no document is open.
- **Parametric Mechanical Component Generators**:
  - **Mounting Brackets & Plates**: Custom rectangular geometry, clearance bolt holes, corner stress-relief fillets.
  - **Flanges**: Circular pipe and shaft flanges with center bore and pitch circle diameter (PCD) bolt hole patterns.
  - **Spur & Helical Gears**: AGMA/ISO standard involute teeth, pitch diameter, face width, bore, and drive keyway.
  - **Connecting Rods & Cranks**: Complete slider-crank link geometries with pin and journal bearing bosses.
  - **Stepped Shafts**: Multi-diameter rotational shafts with chamfers and axial transitions.
  - **Bushings & Plain Bearings**: Precision sleeve bushings and flanged collar bushings.
  - **Dowel & Locating Pins**: Cylindrical pins with chamfered lead-in ends.
  - **Structural Tubes & Profiles**: Square hollow structural sections (SHS) and round pipe/tubing.
  - **Enclosures & Electronic Housings**: Box shells with uniform wall thickness and internal screw mounting posts.
  - **Thermal Heat Sinks**: Baseplates with extruded cooling fin arrays.
- **Granular Parametric CAD Tools**:
  - Full toolset for `create_sketch`, `sketch_rectangle`, `sketch_circle`, `sketch_line`, `feature_extrude_boss`, `feature_extrude_cut`, `feature_revolve_boss`, `feature_fillet`, `feature_chamfer`, `feature_shell`, `feature_circular_pattern`.
- **Physical Inspection & Live Feedback**:
  - `get_mass_properties`: Real-time mass (kg), volume (mm³), surface area (mm²), center of mass.
  - `capture_viewport_preview`: Isometric viewport screenshot saved directly to disk.
- **Direct Python COM Execution (`execute_solidworks_script`)**:
  - The AI can write custom mathematical geometry scripts using `swApp`, `model`, `sketch_mgr`, and `feat_mgr` executed live with error safety.
- **Dual Mode (Live COM + High-Fidelity Simulation)**:
  - Connects to live SolidWorks on Windows.
  - Also includes a built-in simulation adapter (`SOLIDWORKS_MOCK_MODE=1`) for headless development and testing.
