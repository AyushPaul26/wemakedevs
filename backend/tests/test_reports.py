"""Reports must preserve arithmetic, escape evidence, and stage before publication."""
import importlib
import json
import os
from decimal import Decimal

from relay.invoice_compare import compare_invoice
from relay.parsers import ParsedRow, ParsedTable


def reports():
    assert importlib.util.find_spec('relay.reports'), 'ReportService is missing'
    return importlib.import_module('relay.reports')


def result():
    return compare_invoice(ParsedTable('USD', [ParsedRow('gateway-seat', 2, Decimal('110'), 2)]),
                           ParsedTable('USD', [ParsedRow('gateway-seat', 2, Decimal('100'), 2)]))


def test_staged_reports_are_escaped_immutable_and_decimal_correct(tmp_path):
    service = reports().ReportService(tmp_path)
    evidence = [{'source_id':'s', 'version_id':'v', 'chunk_id':'c',
                 'locator':{'row_start':2,'row_end':2}, 'title':'<script>alert(1)</script>'}]
    context = {'run_id':'run-1', 'narrative':'<img src=x onerror=alert(1)>',
               'narrative_mode':'guided', 'company':{'project_label':'Atlas'}}
    staged = service.stage(result(), evidence, context)
    assert len(staged.items) == 2
    first = {item['kind']: item for item in staged.items}
    html = service.path(first['report_html']['blob_key']).read_text()
    assert '220.00' in html and '200.00' in html and '20.00' in html and 'USD' in html
    assert '&lt;script&gt;' in html and '<script>' not in html and '<img ' not in html
    assert 'Guided demo' in html and 'Row 2' in html
    assert 'Atlas' in html and 'Company context' in html
    assert 'not established' in html
    csv = service.path(first['discrepancy_csv']['blob_key']).read_text()
    assert 'gateway-seat,unit_price_mismatch,2,2,100.00,110.00' in csv
    assert service.stage(result(), evidence, context) == staged
    assert all(os.stat(service.path(item['blob_key'])).st_mode & 0o077 == 0 for item in staged.items)
    assert not list(tmp_path.rglob('*.tmp'))
    assert json.dumps(staged.model_dump())


def test_export_neutralizes_spreadsheet_formula_cells():
    escape_cell = reports().safe_csv_cell
    for value in ('=1+2', '+SUM(A1)', '-42', '@SUM(A1)', '\t=1', '\r=1', '\n=1'):
        assert escape_cell(value).startswith("'")
    assert escape_cell('gateway-seat') == 'gateway-seat'


def test_report_paths_reject_traversal_and_staging_detects_corruption(tmp_path):
    module = reports()
    service = module.ReportService(tmp_path)
    staged = service.stage(result(), [], {'run_id':'r'})
    for key in ('../../etc/passwd', '/etc/passwd', 'a/b'):
        try:
            service.path(key)
        except ValueError:
            pass
        else:
            raise AssertionError('unsafe report path accepted')
    artifact = staged.items[0]
    service.path(artifact['blob_key']).write_text('corruption')
    assert not service.verify(staged)
    try:
        service.stage(result(), [], {'run_id':'r'})
    except module.ReportError:
        pass
    else:
        raise AssertionError('corrupt immutable output silently accepted')
