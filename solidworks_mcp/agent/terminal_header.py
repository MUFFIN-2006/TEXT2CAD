"""Responsive drafting illustration for the interactive CAD terminal."""

import math

from PIL import Image, ImageDraw
from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


WORDMARK = (
    " ██████   █████   ██████ ",
    "██       ██   ██  ██   ██",
    "██       ███████  ██   ██",
    "██       ██   ██  ██   ██",
    " ██████  ██   ██  ██████ ",
)
INK = ("", "#487486", "#59b6cb", "#b6f2fb", "#ffb75e")


def _gear_drawing(columns, rows, unicode_art):
    # Braille gives each terminal cell two columns and four rows of drawing dots.
    width, height = columns * 2, rows * 4
    image = Image.new("L", (width, height))
    pen = ImageDraw.Draw(image)
    scale = min((width - 6) / 2.15, (height - 5) / 2.0)

    def project(x, y, z):
        return (round(width / 2 + scale * x),
                round(height * .55 + scale * (.50 * y - .87 * z)))

    def circle(radius, cx=0, cy=0):
        return [(cx + radius * math.cos(i * math.tau / 64),
                 cy + radius * math.sin(i * math.tau / 64)) for i in range(64)]

    def extrude(points, bottom, top, ink, teeth=False):
        lower = [project(x, y, bottom) for x, y in points]
        upper = [project(x, y, top) for x, y in points]
        if teeth:
            # Paint the far walls first so the front teeth occlude their hidden edges.
            edges = sorted(range(len(points)), key=lambda i: points[i - 1][1] + points[i][1])
            for i in edges:
                pen.polygon([lower[i - 1], lower[i], upper[i], upper[i - 1]], fill=0, outline=2)
        else:
            half = len(points) // 2
            silhouette = upper[half:] + upper[:1] + lower[:half + 1]
            pen.polygon(silhouette, fill=0, outline=ink)
        pen.polygon(upper, fill=0, outline=ink)

    def rim(radius, z, ink, cx=0, cy=0):
        points = [project(x, y, z) for x, y in circle(radius, cx, cy)]
        pen.line(points + points[:1], fill=ink)

    # Construction axes remain visible in the gap between the wheel and its hub.
    for y in range(1, height - 1, 6):
        pen.line([(width // 2, y), (width // 2, y + 2)], fill=1)
    axis_y = project(0, 0, 0)[1]
    for x in range(1, width - 1, 8):
        pen.line([(x, axis_y), (x + 3, axis_y)], fill=1)

    outline = []
    for tooth in range(14):
        for phase, radius in ((0, .84), (.16, 1), (.50, 1), (.68, .84)):
            angle = (tooth + phase) * math.tau / 14
            outline.append((radius * math.cos(angle), radius * math.sin(angle)))
    extrude(outline, -.42, 0, 3, teeth=True)
    rim(.76, 0, 2)
    rim(.24, 0, 3)
    for i in range(6):
        angle = (i + .5) * math.tau / 6
        rim(.087, 0, 2, .54 * math.cos(angle), .54 * math.sin(angle))
    extrude(circle(.40), .69, .95, 4)
    rim(.21, .95, 4)

    dots = ((1, 8), (2, 16), (4, 32), (64, 128))
    pixels = image.load()
    drawing = Text(no_wrap=True)
    for row in range(rows):
        if row:
            drawing.append("\n")
        for col in range(columns):
            bits = ink = 0
            for dy, dot_pair in enumerate(dots):
                for dx, dot in enumerate(dot_pair):
                    pixel = pixels[2 * col + dx, 4 * row + dy]
                    if pixel:
                        bits |= dot
                        ink = max(ink, pixel)
            if not bits:
                drawing.append(" ")
            else:
                char = chr(0x2800 + bits) if unicode_art else " .:-=+*#@"[bits.bit_count()]
                drawing.append(char, style=INK[ink])
    return drawing


def show_header(console, simulation):
    mode = "Simulation" if simulation else "Live"
    if not console.is_terminal:
        console.file.write(f"SolidWorks CAD Agent | {mode}\n")
        return

    width = min(console.width, 112)
    tall = console.height >= 15
    try:
        "█⠿".encode(console.encoding)
        unicode_art = not console.legacy_windows
    except UnicodeEncodeError:
        unicode_art = False
    title = Text()
    title.append("S O L I D W O R K S" if width >= 34 else "SOLIDWORKS", style="bold #76d8ea")
    if tall and width >= 34:
        lettering = "\n".join(WORDMARK)
        title.append("\n\n" + (lettering if unicode_art else lettering.replace("█", "#")), style="bold #e3faff")
        title.append("\nD E S I G N E R", style="bold #76d8ea")
    else:
        title.append("\nCAD Designer", style="bold #e3faff")
    title.append("\n\n" if tall else "\n")
    title.append(f" {mode.upper()} ", style="bold #0b1825 on #ffb75e" if simulation else "bold #0b1825 on #81e5be")

    content = Table.grid(padding=(0, 2))
    content.add_column(vertical="middle")
    if width >= 58 and tall:
        columns = min(width - 34, 64)
        rows = min(console.height - 6, 17, max(11, columns // 3))
        content.add_column(vertical="middle")
        content.add_row(title, _gear_drawing(columns, rows, unicode_art))
    else:
        content.add_row(title)
    console.print(Panel(content, box=box.HEAVY if unicode_art else box.ASCII, width=width,
                        padding=(0, 2), style="on #0b1825", border_style="#3988a1"))
    console.print()
