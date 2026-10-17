#!/usr/bin/env python3
"""Inspect read-only by default; apply only an explicit verified offline backup."""

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from relay.database import GraphDatabase  # noqa: E402
from relay.migrations import MigrationService  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph', default=None)
    parser.add_argument('--data-dir', type=Path, default=Path(os.getenv('RELAY_DATA_DIR', '.data')))
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument('--check', action='store_true', help='Read-only preflight (default)')
    operation.add_argument('--apply', type=Path, metavar='BACKUP_MANIFEST')
    parser.add_argument('--quiesced', action='store_true', help='Assert API/executor writers are stopped')
    args = parser.parse_args()
    if args.apply and not args.quiesced:
        parser.error('--apply requires --quiesced; stop API/executor writers first')
    service = MigrationService(GraphDatabase(args.graph), args.data_dir)
    try:
        report = service.apply(args.apply) if args.apply else service.inspect()
    except Exception as exc:
        # Avoid emitting record contents or credentials through driver tracebacks.
        print(f'Migration refused ({type(exc).__name__}); inspect preflight, backup integrity and maintenance state.', file=sys.stderr)
        return 1
    print(report.model_dump_json())
    return 1 if report.violations else 0


if __name__ == '__main__':
    raise SystemExit(main())
