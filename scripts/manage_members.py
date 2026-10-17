#!/usr/bin/env python3
"""Local administrator provisioning; passwords are always entered with getpass.

Run from repository root: PYTHONPATH=backend .venv/bin/python scripts/manage_members.py --help
The operator needs trusted local graph access. This is never an HTTP endpoint.
"""

import argparse
import getpass
import sys

from relay.auth import AuthError, AuthService, ROLES
from relay.database import GraphDatabase


def main(argv=None, *, database=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", help="Graph name; defaults to configured workspace")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Create a member with a hidden password prompt")
    create.add_argument("login")
    create.add_argument("--display-name", required=True)
    create.add_argument("--role", choices=sorted(ROLES), default="operator")
    create.add_argument("--department", choices=["general", "finance"], action="append", default=[])
    change = commands.add_parser("set-role", help="Change role and revoke existing sessions")
    change.add_argument("member_id")
    change.add_argument("role", choices=sorted(ROLES))
    change.add_argument("--department", choices=["general", "finance"], action="append")
    for command in ("disable", "enable", "assign-finance-reviewer"):
        subparser = commands.add_parser(command)
        subparser.add_argument("member_id")
    args = parser.parse_args(argv)
    service = AuthService(database if database is not None else GraphDatabase(graph_name=args.graph))
    try:
        if args.command == "create":
            password = getpass.getpass("New member password: ")
            if password != getpass.getpass("Confirm password: "):
                raise ValueError("Passwords do not match")
            member = service.create_member(args.login, password, args.display_name,
                                           args.role, args.department)
            print(f"Created {member.id} ({member.role})")
        elif args.command == "set-role":
            service.update_member(args.member_id, role=args.role, department_ids=args.department)
            print("Member updated; previous sessions revoked")
        elif args.command in {"disable", "enable"}:
            service.update_member(args.member_id, active=args.command == "enable")
            print("Member updated; previous sessions revoked")
        else:
            policy = service.assign_finance_reviewer(args.member_id)
            print(f"Assigned Finance reviewer under new policy {policy}; previous grants are stale")
    except (ValueError, AuthError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
