"""Extract the supplied five-task Word paper into a private import bundle."""

import argparse
import base64
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def text(node):
    paragraphs = []
    for paragraph in node.findall(".//w:p", NS):
        fragments = []
        for item in paragraph.iter():
            if item.tag.endswith("}t"):
                fragments.append(item.text or "")
            elif item.tag.endswith("}br"):
                fragments.append("\n")
            elif item.tag.endswith("}tab"):
                fragments.append("\t")
        paragraphs.append("".join(fragments))
    return "\n".join(paragraphs)


def prepare(source):
    raw = source.read_bytes()
    with zipfile.ZipFile(source) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    body = text(root)
    public, private = body.split("CONFIDENTIAL JUDGING PACK", 1)
    headings = list(re.finditer(r"(?m)^Q([1-5])\. ", public))
    if [m.group(1) for m in headings] != list("12345"):
        raise ValueError("Expected exactly the five supplied participant tasks.")
    tests = []
    for table in root.findall(".//w:tbl", NS):
        rows = [
            [text(cell) for cell in row.findall("w:tc", NS)]
            for row in table.findall("w:tr", NS)
        ]
        if rows and rows[0][:2] == ["ID", "Input (line 1 = n)"]:
            tests = [
                {
                    "id": r[0],
                    "input": r[1] + "\n",
                    "expected": r[2] + "\n",
                    "purpose": r[3],
                }
                for r in rows[1:]
            ]
    if [t["id"] for t in tests] != [f"H{i:02}" for i in range(1, 11)]:
        raise ValueError("Expected the ten confidential hidden tests.")
    # Check the provided test data without executing any document-supplied code.
    for case in tests:
        values = list(map(int, case["input"].split()))
        if values[0] != len(values) - 1:
            raise ValueError("Hidden test input count differs.")
        if sum(v for v in values[1:] if v % 2 == 0) != int(case["expected"]):
            raise ValueError(
                "Hidden test expected output differs from the stated problem."
            )
    categories = ["OUTPUT", "DEBUG", "FILL", "SHORT", "LOGIC"]
    languages = [["TEXT"], ["C"], ["PYTHON"], ["PYTHON", "C"], ["TEXT"]]
    marks = [15, 25, 20, 30, 10]
    tasks = []
    for i, heading in enumerate(headings):
        end = (
            headings[i + 1].start()
            if i < 4
            else public.index("End of participant question paper")
        )
        prompt = public[heading.start() : end].strip()
        starter = ""
        if i == 3:
            prompt, starter = prompt.split("Optional Python starter code:", 1)
            prompt = prompt.strip()
            starter = starter.strip()
        rubric = {"judging_pack": private.strip()}
        if i == 3:
            rubric["test_cases"] = tests
        tasks.append(
            {
                "public_id": f"Q{i + 1}",
                "category": categories[i],
                "points": str(marks[i]),
                "languages": languages[i],
                "prompt": prompt,
                "starter_code": starter,
                "private_rubric": rubric,
                "version": "event-r3-20261013-v1",
            }
        )
    instructions = public[
        public.index("Instructions") + len("Instructions") : headings[0].start()
    ].strip()
    return {
        "version": 1,
        "source": {
            "filename": source.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "content_base64": base64.b64encode(raw).decode(),
        },
        "instructions": instructions,
        "tasks": tasks,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    bundle = prepare(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(bundle, file, ensure_ascii=False, indent=2)
    print("Prepared 5 tasks, 100 marks and 10 private hidden tests.")
    print("The database importer applies the organizer-approved cut of 11.")
    print("Private bundle:", args.output)


if __name__ == "__main__":
    main()
