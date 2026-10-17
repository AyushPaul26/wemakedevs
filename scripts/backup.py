#!/usr/bin/env python3
"""Back up a quiesced graph and private storage; verify by isolated restoration."""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from relay.database import GraphDatabase  # noqa: E402
from relay.migrations import create_backup, verify_backup  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph', default=None)
    parser.add_argument('--data-dir', type=Path, default=Path(os.getenv('RELAY_DATA_DIR', '.data')))
    parser.add_argument('--quiesced', action='store_true', help='Assert API/executor writers are stopped')
    parser.add_argument('--verify', type=Path, metavar='MANIFEST', help='Repeat isolated restore without changing live data')
    args = parser.parse_args()
    if not args.verify and not args.quiesced:
        parser.error('Backup requires --quiesced; stop API/executor writers first')
    database = GraphDatabase(args.graph)
    try:
        if args.verify:
            verify_backup(database, args.verify)
            print(json.dumps({'restore_verified': True}))
        else:
            manifest = create_backup(database, args.data_dir, quiesced=args.quiesced)
            print(json.dumps({'manifest': str(manifest), 'restore_verified': True}))
    except Exception as exc:
        print(f'Backup refused ({type(exc).__name__}); check graph, private storage, checksums and quiescence.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
