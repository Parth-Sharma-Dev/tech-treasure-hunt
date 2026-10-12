"""Prepare a derived export by removing only Overview formulas with cached values.

The original stays untouched. Participant Data and all other sheet bytes stay
unchanged. The derived file still passes the application's normal validation.
"""

import argparse
import hashlib
import io
import posixpath
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from competition.wayground_workbook import read_workbook

MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS = {'m': MAIN}


def prepare(raw):
    output = io.BytesIO()
    removed = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        targets = {
            node.attrib['Id']: node.attrib['Target']
            for node in ET.fromstring(source.read('xl/_rels/workbook.xml.rels'))
            if node.attrib.get('TargetMode') != 'External'
        }
        overview = None
        for sheet in ET.fromstring(source.read('xl/workbook.xml')).findall('m:sheets/m:sheet', NS):
            if sheet.attrib['name'] == 'Overview':
                target = targets[sheet.attrib['{' + REL + '}id']]
                overview = posixpath.normpath(
                    target.lstrip('/') if target.startswith('/') else 'xl/' + target
                )
        if overview is None or not overview.startswith('xl/worksheets/'):
            raise ValueError('Expected an Overview worksheet.')
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as derived:
            for item in source.infolist():
                content = source.read(item.filename)
                if item.filename == overview:
                    root = ET.fromstring(content)
                    for cell in root.findall('.//m:c', NS):
                        formula = cell.find('m:f', NS)
                        if formula is not None:
                            if cell.find('m:v', NS) is None:
                                raise ValueError('Overview formula has no cached value.')
                            cell.remove(formula)
                            removed += 1
                    content = ET.tostring(root, encoding='utf-8', xml_declaration=True)
                derived.writestr(item.filename, content)
        with zipfile.ZipFile(io.BytesIO(output.getvalue())) as derived:
            for item in source.infolist():
                if item.filename != overview:
                    assert source.read(item.filename) == derived.read(item.filename)
    result = output.getvalue()
    metadata, participants = read_workbook(result)
    return result, removed, metadata, len(participants)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    result, removed, metadata, count = prepare(raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as file:
        file.write(result)
    print('Source SHA256:', hashlib.sha256(raw).hexdigest())
    print('Derived SHA256:', hashlib.sha256(result).hexdigest())
    print('Overview formulas removed:', removed)
    print('Participant rows:', count, 'Question count:', metadata['question_count'])
    print('Participant sheet bytes unchanged. Output:', args.output)


if __name__ == '__main__':
    main()
