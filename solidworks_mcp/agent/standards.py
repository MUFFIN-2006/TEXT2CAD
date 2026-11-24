"""Read dimensional sheets from the installed ANSI Inch and ANSI Metric Toolbox libraries."""

from contextlib import closing
from functools import lru_cache
from collections import Counter
import re
import sqlite3
from urllib.parse import quote

from .offline_standards import DIRECTORY, reference_files, toolbox_path

ASME = "https://www.asme.org/codes-standards/find-codes-standards"
ANSI = "https://webstore.ansi.org/"
MEASUREMENT_POLICY = (
    "Use dimensions from the matching standard row by default once the part, nominal size and variant are known. "
    "There is no need to ask whether the user wants standard or custom measurements. "
    "Apply any dimensions the user gives during creation to the current design, including revisions in replies. "
    "Keep the other applicable reference dimensions and identify any departures as custom. "
    "Ask only for unresolved requirements or incompatible constraints, including a separate requirement for strict compliance."
)
SOURCES = {
    "B18.22M": "b18-22m-metric-plain-washers",
    "B17.2": "b17-2-woodruff-keys-keyseats",
    "B18.21.1": "b18-21-1-washers-helical-spring-lock-tooth-lock-plain-washers",
    "B18.2.3.5M": "b18-2-3-5m-metric-hex-bolts-errata",
    "B1.1": "b1-1-unified-inch-screw-threads-un-unr-thread-form",
}
DESIGNATION = re.compile(r"\bB\d+(?:\.\d+)+M?\b", re.I)


def _identifier(name):
    return '"' + name.replace('"', '""') + '"'


def _connection(path):
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def _tokens(text):
    return {w.removesuffix("s") for w in re.findall(r"[a-z]+|\d+", text.lower())}


@lru_cache(maxsize=8)
def _families(path, mtime, library=""):
    result = {}
    with closing(_connection(path)) as db:
        for std in db.execute("SELECT * FROM Standards WHERE enabled=1"):
            name = std["Name"].replace("®", "").casefold()
            if not library and name not in {"ansi inch", "ansi metric"}:
                continue
            if library and library not in {"all", name}:
                continue
            prefix = std["TableNamePrefix"]
            types = {r["ID"]: r["Name"] for r in db.execute("SELECT * FROM " + _identifier(std["TypeID"]))}
            for category in db.execute("SELECT * FROM " + _identifier(std["CategoryID"]) + " WHERE enabled=1"):
                table = category["TypeID"]
                for row in db.execute("SELECT * FROM " + _identifier(table) + " WHERE enabled=1"):
                    key = f"{table}:{row['key']}".upper()
                    code = DESIGNATION.search((row["Title"] or "") + " " + (row["Name"] or ""))
                    result[key] = dict(family_id=key, family=row["Title"], variant=row["Name"],
                                       category=category["Name"], group=types.get(row["ID"], ""),
                                       system=std["Name"], length_unit=row["DataTableUnits"] or std["DefaultUnits"],
                                       designation=code[0].upper() if code else None,
                                       table=row["DataTable"].replace("+", prefix),
                                       config=row["ConfigurationTable"].replace("+", prefix), prefix=prefix)
    return result


def _source(code, query):
    if code in SOURCES:
        return ASME + "/" + SOURCES[code]
    return ASME + "?query=" + quote(code or query)


def _summary(record):
    public = {k: v for k, v in record.items() if k not in {"config", "prefix"}}
    public["publisher_lookup"] = (_source(record["designation"], record["family"])
                                  if record["system"] in {"Ansi Inch", "Ansi Metric"} else "")
    if record["designation"] == "B18.2.3.5M":
        public["publication_status"] = "ASME lists this metric hex bolt publication as historical."
    return public


def _matching(records, query, system):
    code = DESIGNATION.search(query)
    description = re.sub(r"\bM\d+(?:\.\d+)?\b|\b\d+/\d+\b", "", DESIGNATION.sub("", query), flags=re.I)
    words = _tokens(description) - {"ansi", "asme", "inch", "metric", "for", "the", "a", "make", "design", "plan", "new"}
    best = []
    for row in records:
        if system and row["system"].lower() != "ansi " + system:
            continue
        if code and code[0].upper() != row["designation"]:
            continue
        title = _tokens(DESIGNATION.sub("", row["family"])) - {"ansi", "asme"}
        common = words & title
        if not code and not common - {"inch", "metric", "regular", "type", "flat", "a", "b", "size"}:
            if not words.intersection(_tokens(row["category"] + " " + row["group"])):
                continue
        score = (len(common), len(words & _tokens(row["variant"])), -len(title - words))
        best.append((score, row))
    best.sort(key=lambda item: item[0], reverse=True)
    # Show variants when only the group or standard is known. Never choose a default row from a list.
    return [r for _, r in best]


def lookup_dimensions(query="", family_id="", filters=None, option="", offset=0, library=""):
    """Return matching families or a page of source rows for an explicitly selected sheet."""
    path = toolbox_path()
    code = DESIGNATION.search(query)
    base = dict(source="SOLIDWORKS Toolbox", database=str(path), edition="unverified",
                publisher_lookup=_source(code[0].upper() if code else None, query), ansi_store=ANSI)
    if library and not library.lower().startswith("ansi"):
        base["publisher_lookup"] = ""
    if not 0 <= offset < 2**31:
        return dict(base, status="error", message="Offset must be a nonnegative page position below 2^31.")
    try:
        selected = library.replace("®", "").strip().casefold()
        records = _families(path, path.stat().st_mtime_ns, selected or ("all" if family_id else ""))
        if not family_id:
            metric = re.search(r"\bM\d+(?:\.\d+)?\b|\bmetric\b", query, re.I)
            inch = re.search(r"\binch(?:es)?\b|\b\d+/\d+\b", query, re.I)
            system = "metric" if metric and not inch else "inch" if inch and not metric else ""
            rows = _matching(records.values(), query, "" if library else system) if query.strip() else list(records.values())
            if not rows and query.strip():
                local = reference_files(code[0] if code else query)
                base["offline_pages"] = local["page_matches"][:5]
                base["offline_documents"] = local["documents"][:5]
            return dict(base, status="families" if rows else "no_match", total=len(rows),
                        families=[_summary(r) for r in rows[offset:offset+12]])
        family_id = family_id.upper()
        if family_id not in records:
            return dict(base, status="no_match", message="Unknown sheet. Search for its family first.")
        sheet = records[family_id]
        if code and sheet["designation"] != code[0].upper():
            return dict(base, status="no_match", message="This family does not identify the requested standard.")
        base.update(_summary(sheet))
        with closing(_connection(path)) as db:
            options = {}
            if sheet["config"]:
                for r in db.execute("SELECT * FROM " + _identifier(sheet["config"])):
                    source = r["AltDataSource"]
                    if r["Grid_Item_Name"] and source and source.startswith("+"):
                        options[r["Grid_Item_Name"]] = source.replace("+", sheet["prefix"], 1)
            base["options"] = options
            if option and option not in options:
                return dict(base, status="error", message="Select an option listed on this sheet.")
            table = options[option] if option else sheet["table"]
            base["table"] = table
            quoted = _identifier(table)
            columns = {c[0].lower(): c[0] for c in db.execute("SELECT * FROM " + quoted + " LIMIT 0").description}
            hidden = {"enabled", "key", "sort", "sortorder", "name to match"}
            base["columns"] = [v for k, v in columns.items() if k not in hidden]
            clauses = ['"enabled"=1'] if "enabled" in columns else []
            values = []
            for k, v in (filters or {}).items():
                if k.lower() not in columns or k.lower() in hidden:
                    return dict(base, status="error", message=f"Unknown measurement field {k}.")
                clauses.append("trim(CAST(" + _identifier(columns[k.lower()]) + " AS TEXT)) = ? COLLATE NOCASE")
                values.append(str(v).strip())
            sql = " FROM " + quoted + (" WHERE " + " AND ".join(clauses) if clauses else "")
            total = db.execute("SELECT count(*)" + sql, values).fetchone()[0]
            rows = db.execute("SELECT *" + sql + " ORDER BY rowid LIMIT 8 OFFSET ?", [*values, offset])
            return dict(base, status="rows" if total else "no_match", total=total,
                        rows=[{c: row[c] for c in base["columns"]} for row in rows])
    except (OSError, sqlite3.Error, KeyError, IndexError) as exc:
        return dict(base, status="unavailable", message=f"Could not read the Toolbox sheet. {exc}")


def offline_inventory(query="", offset=0):
    if offset < 0:
        raise ValueError("Use a nonnegative document offset.")
    path = toolbox_path()
    docs = reference_files(query, offset)
    try:
        families = _families(path, path.stat().st_mtime_ns, "all")
        counts = dict(Counter(f["system"] for f in families.values()))
    except (OSError, sqlite3.Error) as exc:
        return dict(docs, status="unavailable", database=str(path), message=str(exc))
    return dict(docs, status="success", database=str(path), snapshot=path == DIRECTORY / "toolbox.sqlite",
                libraries=counts, families=sum(counts.values()))


def design_reference(query):
    """Select a size row only for an identified family and measurement system."""
    found = lookup_dimensions(query)
    families = found.get("families", [])
    size = re.search(r"\bM(\d+(?:\.\d+)?)\b", query, re.I)
    fraction = re.search(r"(?<![\w/])(\d+/\d+)(?![\w/])", query)
    if (not size and not fraction) or not families:
        return found
    words = _tokens(query)
    exact = []
    for family in families:
        name = family["family"].split(" - ")[0].split(" (")[0]
        if _tokens(name) <= words:
            exact.append(family)
    if len(exact) != 1:
        return found
    family_id = exact[0]["family_id"]
    nominal = size[0].upper() if size else fraction[1]
    filters = {"size": nominal}
    if fraction and not size:
        thread = re.match(r"\s*-\s*(\d+)\b", query[fraction.end():])
        if thread:
            filters["pitch"] = thread[1]
    result = lookup_dimensions(query, family_id, filters)
    if size and result["status"] == "no_match":
        result = lookup_dimensions(query, family_id, {"size": size[1]})
    return result


def format_reference(result):
    if result["status"] == "families":
        lines = [f"{r['family_id']}  {r['system']}  {r['family']}" for r in result["families"]]
        return "\n".join(lines + ["Select the applicable family and size. " + result["publisher_lookup"]])
    if result["status"] == "rows":
        header = f"{result['system']} | {result['family']} | length unit {result['length_unit']}"
        rows = [", ".join(f"{k}={v}" for k, v in row.items() if v is not None) for row in result["rows"]]
        overrides = ", ".join(f"{k.replace('_', ' ')} {v:g} mm" for k, v in result.get("custom_dimensions_mm", {}).items())
        return "\n".join(filter(None, [header, *rows, f"Source: SOLIDWORKS Toolbox / {result['table']}",
                    f"Custom model dimensions: {overrides}" if overrides else "",
                    result.get("publication_status"), "Toolbox edition unverified. " + result["publisher_lookup"]]))
    message = result.get("message") or "No matching installed measurement row. Supply the applicable sheet or dimensions."
    pages = [f"{r['path']} (PDF page {r['page']})" for r in result.get("offline_pages", [])]
    files = [f"{r['kind']}: {r['path']}" for r in result.get("offline_documents", [])]
    return "\n".join(filter(None, [message, *files, *pages, result["publisher_lookup"]]))
