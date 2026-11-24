"""Prepare the project's local standards library. No network service is required."""

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from tempfile import NamedTemporaryFile
from urllib.request import urlopen


DIRECTORY = Path(__file__).resolve().parents[2] / "offline-standards"
INSTALLED = Path(r"C:\SOLIDWORKS Data\lang\english\swbrowser.sldedb")
DOCUMENTS = {
    "ASME-B16.11-2021-contents.pdf": "https://www.asme.org/getmedia/1349c5c1-3243-46be-9821-51d4e89c56a7/b16-11_2021_toc.pdf",
    "ASME-B16.5-2020-preview.pdf": "https://www.asme.org/getmedia/5cc627a0-d379-4186-89b4-4f552381a98f/b16-5_pipe-flanges-and-flanged-fittings-2020.pdf",
    "ASME-B18.2.2-2022-contents.pdf": "https://www.asme.org/getmedia/a5d59a0e-7d26-4b87-aa17-d45e8fcf48e4/b18-2-2_2022_toc.pdf",
    "ASME-B36.10-2022-contents.pdf": "https://www.asme.org/getmedia/3b3dad99-fbc1-417c-af2d-1058dfc8c55b/b36-10_2022_toc.pdf",
    "InfraBuild-Pipe-and-Fittings.pdf": "https://www.infrabuild.com/wp-content/uploads/sites/8/2022/02/IBSC_Pipe2020Fittings20Data20Charts_A4.pdf",
    "Unbrako-Engineering-Guide.pdf": "https://unbrako.com/docs/engguide.pdf",
    "Tsubaki-Roller-Chain-Catalog.pdf": "https://www.ustsubaki.com/wp-content/uploads/RCD-Catalog-Single-Pages-compressed-1.pdf",
    "Trelleborg-AS568-O-Rings.pdf": "https://www.trelleborg.com/en/seals/-/media/tss-media-repository/tss_website/pdf-and-other-literature/catalogs/as568_o-rings_en.pdf",
    "NTN-Ball-and-Roller-Bearings.pdf": "https://ntnamericas.com/wp-content/uploads/2020/04/ntn_a1000xi_ball_and_roller_bearings_lowres.pdf",
    "Lee-Spring-Catalog.pdf": "https://www.leespring.com/sites/default/files/2019-07/Lee_Spring_Catalog_US_Eng.pdf",
}


def toolbox_path():
    override = os.environ.get("SOLIDWORKS_TOOLBOX_DB")
    if override:
        return Path(override).expanduser().resolve()
    snapshot = DIRECTORY / "toolbox.sqlite"
    return snapshot if snapshot.is_file() else INSTALLED.resolve()


def prepare_snapshot(source, target):
    source = source.resolve(strict=True)
    if source == target.resolve():
        raise ValueError("Select the installed source database for the refresh.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=target.parent, delete=False, suffix=".tmp") as tmp:
        staging = Path(tmp.name)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src, closing(sqlite3.connect(staging)) as dest:
            src.backup(dest)
            if not dest.execute("SELECT 1 FROM Standards WHERE enabled=1 LIMIT 1").fetchone():
                raise ValueError("Source has no enabled Toolbox standards.")
            if dest.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Snapshot failed the SQLite integrity check.")
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)


def index_public_guides():
    target = DIRECTORY / "pages.sqlite"
    with NamedTemporaryFile(dir=DIRECTORY, delete=False, suffix=".tmp") as tmp:
        staging = Path(tmp.name)
    try:
        if target.is_file():
            with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as src, closing(sqlite3.connect(staging)) as dst:
                src.backup(dst)
        _index_guides_into(staging)
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)


def _index_guides_into(staging):
    from pypdf import PdfReader

    with closing(sqlite3.connect(staging)) as db:
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(filename UNINDEXED, page UNINDEXED, content)")
        db.execute("CREATE TABLE IF NOT EXISTS indexed(filename TEXT PRIMARY KEY, size INTEGER, stamp INTEGER)")
        for name in DOCUMENTS:
            path = DIRECTORY / name
            if not path.is_file() or name.startswith("ASME-"):
                continue
            stamp = path.stat()
            previous = db.execute("SELECT size, stamp FROM indexed WHERE filename=?", (name,)).fetchone()
            if previous == (stamp.st_size, stamp.st_mtime_ns):
                continue
            with path.open("rb") as file, db:
                reader = PdfReader(file)
                db.execute("DELETE FROM pages WHERE filename=?", (name,))
                for i, page in enumerate(reader.pages, 1):
                    content = (page.extract_text() or "").strip()
                    if content:
                        db.execute("INSERT INTO pages VALUES(?,?,?)", (name, i, content))
                db.execute("INSERT OR REPLACE INTO indexed VALUES(?,?,?)", (name, stamp.st_size, stamp.st_mtime_ns))


def download_public_guides():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    for name, url in DOCUMENTS.items():
        target = DIRECTORY / name
        if target.is_file():
            continue
        with NamedTemporaryFile(dir=DIRECTORY, delete=False, suffix=".part") as tmp:
            staging = Path(tmp.name)
        try:
            with urlopen(url, timeout=90) as response, staging.open("wb") as output:
                shutil.copyfileobj(response, output)
            with staging.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise ValueError(f"The publisher did not return a PDF for {name}.")
                stream.seek(max(0, staging.stat().st_size - 4096))
                if b"%%EOF" not in stream.read():
                    raise ValueError(f"Incomplete PDF download for {name}.")
            os.replace(staging, target)
        finally:
            staging.unlink(missing_ok=True)


def _page_matches(query, offset):
    index = DIRECTORY / "pages.sqlite"
    words = re.findall(r"\w+", query)
    if not words or not index.is_file():
        return []
    expression = " AND ".join(f'"{w}"' for w in words)
    with closing(sqlite3.connect(index.as_uri() + "?mode=ro", uri=True)) as db:
        rows = db.execute("SELECT filename,page,snippet(pages,2,'','',' ... ',22) FROM pages "
                          "WHERE pages MATCH ? ORDER BY rank LIMIT 30 OFFSET ?", (expression, offset))
        return [dict(path=str(DIRECTORY / name), page=page, excerpt=text, source=DOCUMENTS[name])
                for name, page, text in rows if name in DOCUMENTS and (DIRECTORY / name).is_file()]


def reference_files(query="", offset=0):
    docs = [dict(path=str(DIRECTORY / name), source=url,
                 kind="ASME public preview" if name.startswith("ASME-") else "Manufacturer guide")
            for name, url in DOCUMENTS.items() if (DIRECTORY / name).is_file()]
    config = DIRECTORY / "licensed-folder.txt"
    folder = os.environ.get("SOLIDWORKS_STANDARDS_FOLDER") or (
        config.read_text(encoding="utf-8").strip() if config.is_file() else "")
    warning = None
    if folder:
        root = Path(folder).expanduser()
        if root.is_dir():
            for file in sorted(root.rglob("*")):
                if file.suffix.lower() in {".pdf", ".xlsx", ".xls", ".csv"} and file.is_file():
                    docs.append(dict(path=str(file.resolve()), kind="User-supplied reference"))
        else:
            warning = f"Reference folder is unavailable: {folder}"
    if query:
        def search_text(value):
            return re.sub(r"[-_\s]+", " ", value.casefold()).strip()

        topic = search_text(query)
        docs = [d for d in docs if topic and topic in search_text(Path(d["path"]).stem)]
    return dict(total=len(docs), documents=docs[offset:offset+30], page_matches=_page_matches(query, offset),
                licensed_folder=folder or None, warning=warning)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(os.environ.get("SOLIDWORKS_TOOLBOX_DB") or INSTALLED))
    parser.add_argument("--licensed-folder", type=Path, help="Register a reference folder on this PC.")
    parser.add_argument("--download-public", action="store_true", help="Download missing public publisher guides.")
    args = parser.parse_args()
    folder = args.licensed_folder
    if folder and not folder.is_dir():
        parser.error("The reference folder does not exist.")
    target = DIRECTORY / "toolbox.sqlite"
    prepare_snapshot(args.source, target)
    if args.download_public:
        download_public_guides()
    index_public_guides()
    if folder:
        (DIRECTORY / "licensed-folder.txt").write_text(str(folder.resolve()), encoding="utf-8")
    print(json.dumps(dict(database=str(target), bytes=target.stat().st_size, **reference_files()), indent=2))


if __name__ == "__main__":
    main()
