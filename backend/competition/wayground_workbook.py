"""Bounded, non-executing OOXML reader for the supplied Wayground export layout."""

import io
import posixpath
import re
import zipfile
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from xml.etree import ElementTree as ET

MAX_BYTES = 1_000_000
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"m": MAIN}


def milliseconds(value):
    try:
        if ":" in value:
            parts = value.split(":")
            if len(parts) != 3 or not re.fullmatch(
                r"[0-9]+:[0-5][0-9]:[0-5][0-9](?:\.[0-9]+)?", value
            ):
                raise ValueError()
            hours, minutes, seconds = map(Decimal, parts)
            amount = (hours * 3600 + minutes * 60 + seconds) * 1000
        else:
            amount = Decimal(value) * Decimal(86400000)
        if not amount.is_finite() or not 0 <= amount <= 86400000:
            raise ValueError()
        return int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        raise ValueError(
            "Invalid exported answering duration; use Excel day fractions or hh:mm:ss."
        ) from None


def read_workbook(content):
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_BYTES:
        raise ValueError("Upload a Wayground .xlsx file of at most 1 MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            items = archive.infolist()
            if len(items) > 1000 or sum(i.file_size for i in items) > 20_000_000:
                raise ValueError("The expanded workbook exceeds its limits.")

            def xml(path):
                raw = archive.read(path)
                if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                    raise ValueError("Workbook entity declarations are unsupported.")
                return ET.fromstring(raw)

            strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                strings = [
                    "".join(node.itertext())
                    for node in xml("xl/sharedStrings.xml").findall("m:si", NS)
                ]
            targets = {
                node.attrib["Id"]: node.attrib["Target"]
                for node in xml("xl/_rels/workbook.xml.rels")
                if node.attrib.get("TargetMode") != "External"
            }
            sheets = {}
            for sheet in xml("xl/workbook.xml").findall("m:sheets/m:sheet", NS):
                target = targets[sheet.attrib["{" + REL + "}id"]]
                path = posixpath.normpath(
                    target.lstrip("/") if target.startswith("/") else "xl/" + target
                )
                if not path.startswith("xl/worksheets/"):
                    raise ValueError("Unsupported worksheet relationship.")
                rows = []
                for row in xml(path).findall("m:sheetData/m:row", NS):
                    if len(rows) >= 2002:
                        raise ValueError("Workbook supports at most 2000 participant rows.")
                    cells = {}
                    for cell in row.findall("m:c", NS):
                        if cell.find("m:f", NS) is not None:
                            raise ValueError(
                                "Formula cells are not accepted; export original report values."
                            )
                        ref = cell.attrib["r"]
                        column = re.match(r"[A-Z]+", ref).group()
                        if cell.attrib.get("t") == "inlineStr":
                            value = "".join(cell.find("m:is", NS).itertext())
                        else:
                            value = cell.findtext("m:v", default="", namespaces=NS)
                            if cell.attrib.get("t") == "s" and value:
                                value = strings[int(value)]
                        if len(value) > 65536:
                            raise ValueError("A workbook cell exceeds its limit.")
                        cells[column] = value
                    rows.append((int(row.attrib["r"]), cells))
                sheets[sheet.attrib["name"]] = rows
            rows = sheets.get("Participant Data")
            if not rows or len(rows) < 2:
                raise ValueError("The export needs a Participant Data worksheet with players.")
            columns = {v.strip(): k for k, v in rows[0][1].items()}
            required = [
                "Player Name",
                "Score",
                "Total Time Taken",
                "Correct",
                "Incorrect",
                "Total Questions Attempted",
                "Unattempted",
                "Yet to be graded",
                "Partially correct",
                "Ungraded",
            ]
            if any(name not in columns for name in required) or len(columns) != len(rows[0][1]):
                raise ValueError(
                    "Participant Data headers do not match the supplied Wayground export."
                )
            participants, counts = [], set()
            for row_number, cells in rows[1:]:
                if not any(cells.values()):
                    continue
                values = {name: cells.get(columns[name], "") for name in required}
                name = values["Player Name"].strip()
                if not name or len(name) > 200:
                    raise ValueError("Every participant needs a bounded Player Name.")
                score = Decimal(values["Score"])
                if (
                    not score.is_finite()
                    or not 0 <= score <= Decimal("9999999.999")
                    or score.as_tuple().exponent < -3
                ):
                    raise ValueError(
                        "Exported Score is not a valid nonnegative platform point value."
                    )
                stats = {}
                for key in required[3:]:
                    if not re.fullmatch(r"[0-9]+", values[key]):
                        raise ValueError("Exported question counts must be nonnegative integers.")
                    stats[key] = int(values[key])
                total = stats["Total Questions Attempted"] + stats["Unattempted"]
                if (
                    not 1 <= total <= 500
                    or sum(
                        stats[k]
                        for k in [
                            "Correct",
                            "Incorrect",
                            "Yet to be graded",
                            "Partially correct",
                            "Ungraded",
                            "Unattempted",
                        ]
                    )
                    != total
                ):
                    raise ValueError("Participant question counts are inconsistent.")
                counts.add(total)
                participants.append(
                    {
                        "source_row": row_number,
                        "player_name": name,
                        "score": str(score),
                        "answer_time_ms": milliseconds(values["Total Time Taken"]),
                        "counts": stats,
                    }
                )
            if len(counts) != 1 or not participants:
                raise ValueError("Participant rows disagree on the quiz question count.")
            return {
                "question_count": counts.pop(),
                "source_sheet": "Participant Data",
                "time_unit": "excel_day_fraction_or_hh:mm:ss",
                "score_column": "Score",
            }, participants
    except (
        zipfile.BadZipFile,
        KeyError,
        IndexError,
        ET.ParseError,
        InvalidOperation,
        AttributeError,
    ):
        raise ValueError("Invalid or unsupported Wayground workbook.") from None
