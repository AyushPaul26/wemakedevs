"""Private immutable report staging; graph publication belongs to WorkflowStore."""
import csv
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from html import escape
import io
import json
import os
from pathlib import Path
import re
import tempfile

from relay.workflow_models import StagedArtifacts


class ReportError(RuntimeError):
    """A report could not be staged or an immutable file failed verification."""


def safe_csv_cell(value) -> str:
    text = '' if value is None else str(value)
    return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else text


def _plain(value):
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json')
    return asdict(value) if is_dataclass(value) else value


class ReportService:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)

    def path(self, key):
        if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{64}\.(html|csv)', key):
            raise ValueError('Invalid artifact storage key')
        path = self.root / key
        if path.is_symlink():
            raise ValueError('Invalid artifact storage path')
        return path

    def _put(self, content, extension):
        data = content.encode('utf-8')
        digest = sha256(data).hexdigest()
        key = f'{digest}.{extension}'
        destination = self.path(key)
        if destination.exists():
            if sha256(destination.read_bytes()).hexdigest() != digest:
                raise ReportError('An immutable report failed verification')
            return key, digest, len(data)
        descriptor, temporary = tempfile.mkstemp(dir=self.root, suffix='.tmp')
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if sha256(destination.read_bytes()).hexdigest() != digest:
                    raise ReportError('An immutable report failed verification')
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            os.unlink(temporary)
        return key, digest, len(data)

    def stage(self, result, evidence, context) -> StagedArtifacts:
        result = _plain(result)
        evidence = [_plain(ref) for ref in evidence]
        findings = [_plain(finding) for finding in result['findings']]
        def e(value):
            return escape(str(value if value is not None else ''), quote=True)
        rows = ''.join('<tr>' + ''.join(f'<td>{e(finding.get(key))}</td>' for key in
                       ('item_id', 'kind', 'invoice_row', 'order_row', 'expected', 'actual')) + '</tr>'
                       for finding in findings)
        citations = []
        for ref in evidence:
            locator = ref.get('locator') or {}
            label = (f"Row {locator['row_start']}" if locator.get('row_start') else
                     f"Page {locator['page']}" if locator.get('page') else
                     f"Paragraph {locator['paragraph']}" if locator.get('paragraph') else 'Source')
            citations.append(f"<li>{e(ref.get('title'))}: {e(label)} "
                             f"(version {e(ref.get('version_id'))}; chunk {e(ref.get('chunk_id'))})</li>")
        company = context.get('company') or {}
        labels = {node['id']:node.get('label', node['id']) for node in company.get('nodes', [])}
        connections = ''.join(f"<li>{e(labels.get(edge['source'], edge['source']))} "
                              f"{e(edge.get('relation'))} "
                              f"{e(labels.get(edge['target'], edge['target']))}</li>"
                              for edge in company.get('edges', []))
        owner = company.get('owner_entity_id')
        company_html = ('<h2>Company context</h2>'
                        f"<p>Project: {e(company.get('project_label') or company.get('project_id') or 'Not recorded')}. "
                        f"Case owner: {e(labels.get(owner, owner) if owner else 'Unassigned')}.</p>"
                        f'<ul>{connections}</ul>')
        mode = 'Live model' if context.get('narrative_mode') == 'live' else 'Guided demo'
        html = ("<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
                "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
                '<title>Invoice reconciliation</title><main><h1>Invoice reconciliation</h1>'
                f"<p>Run {e(context.get('run_id'))}</p><p>Narrative mode: {mode}</p>"
                f"<p>Invoice: {e(result['invoice_total'])} {e(result['currency'])}; "
                f"purchase order: {e(result['order_total'])} {e(result['currency'])}; "
                f"difference: {e(result['difference'])} {e(result['currency'])}.</p>"
                '<p>A launch blocker is not established by this financial comparison. '
                'Company connections alone do not prove a launch dependency or gating policy.</p>'
                f"<p>{e(context.get('narrative', 'Comparison calculated from the selected source rows.'))}</p>"
                '<table><caption>Discrepancies</caption><thead><tr><th>Item</th><th>Finding</th>'
                '<th>Invoice row</th><th>Order row</th><th>Expected</th><th>Actual</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>{company_html}<h2>Evidence</h2><ul>{"".join(citations)}</ul></main></html>')
        stream = io.StringIO(newline='')
        writer = csv.writer(stream, lineterminator='\n')
        keys = ('item_id', 'kind', 'invoice_row', 'order_row', 'expected', 'actual')
        writer.writerow(keys)
        for finding in findings:
            writer.writerow([safe_csv_cell(finding.get(key)) for key in keys])
        items = []
        for kind, text, extension, mime in [('report_html', html, 'html', 'text/html'),
                                           ('discrepancy_csv', stream.getvalue(), 'csv', 'text/csv')]:
            key, digest, size = self._put(text, extension)
            identity = sha256(json.dumps([context.get('run_id'), context.get('effect_key'), kind, digest],
                                        separators=(',', ':')).encode()).hexdigest()
            items.append({'id':f'artifact:{identity}', 'kind':kind, 'blob_key':key,
                          'content_hash':digest, 'byte_size':size, 'mime':mime,
                          'classification':'finance', 'audience':context.get('output_audience', [])})
        return StagedArtifacts(items=items)

    def verify(self, staged) -> bool:
        items = staged.items if hasattr(staged, 'items') and not isinstance(staged, dict) else staged['items']
        try:
            return bool(items) and all(sha256(self.path(item['blob_key']).read_bytes()).hexdigest()
                                       == item['content_hash'] for item in items)
        except (OSError, ValueError, KeyError):
            return False
