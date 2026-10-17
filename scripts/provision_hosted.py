#!/usr/bin/env python3
"""Opt-in offline demo identities, after storage readiness and before HTTP starts.

Secrets come only from the host environment. A completed graph marker makes
future boots read-only; a partial marker requires local administrator review.
"""
import argparse
import os
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from relay.auth import AuthService, normalized_login  # noqa: E402
from relay.database import GraphDatabase  # noqa: E402
from relay.migrations import ensure_schema  # noqa: E402

MARKER_ID = 'meridian:1'


class ProvisioningError(RuntimeError):
    """Safe provisioning failure: never include credential or environment values."""


def _logins(environ):
    try:
        names = tuple(normalized_login(environ.get(key, default)) for key, default in (
            ('RELAY_BOOTSTRAP_ADMIN_LOGIN','owner'), ('RELAY_OPERATOR_LOGIN','demo-operator'),
            ('RELAY_FINANCE_AUDITOR_LOGIN','demo-auditor')))
    except (TypeError, ValueError):
        raise ProvisioningError('Hosted demo logins are invalid') from None
    if len(set(names)) != 3:
        raise ProvisioningError('Hosted owner, operator, and Finance logins must be distinct')
    return names


def _secrets(environ):
    values = tuple(environ.get(name) for name in ('RELAY_ACCESS_PASSWORD',
        'RELAY_OPERATOR_PASSWORD','RELAY_FINANCE_AUDITOR_PASSWORD'))
    if any(not isinstance(value,str) or not 16 <= len(value) <= 1024
           or len(set(value)) < 6 or not value.strip() for value in values):
        raise ProvisioningError('Initial hosted provisioning requires three strong configured passwords of 16–1024 characters')
    if len(set(values)) != 3:
        raise ProvisioningError('Hosted owner, operator, and Finance passwords must be distinct')
    return values


def _enabled(environ):
    value = environ.get('RELAY_PROVISION_DEMO_ACCOUNTS','0')
    if value not in {'0','1'}:
        raise ProvisioningError('RELAY_PROVISION_DEMO_ACCOUNTS must be exactly 0 or 1')
    return value == '1'


def provision(database, environ=None, *, quiesced=False):
    environ = os.environ if environ is None else environ
    if not _enabled(environ):
        return False
    if not quiesced:
        raise ProvisioningError('Hosted provisioning requires --quiesced before HTTP and executor startup')
    try:
        ensure_schema(database)
    except Exception:
        raise ProvisioningError('Hosted provisioning requires completed storage/schema readiness') from None
    owner_login, operator_login, auditor_login = _logins(environ)
    markers = database.query('MATCH (m:HostedDemoBootstrap {id:$id}) RETURN properties(m)',{'id':MARKER_ID})
    if markers:
        if len(markers)!=1 or markers[0][0].get('status')!='completed':
            raise ProvisioningError('Hosted demo provisioning is partial; local administrator review is required')
        record = markers[0][0]
        if [record.get(key) for key in ('owner_login','operator_login','auditor_login')] != [owner_login,operator_login,auditor_login]:
            raise ProvisioningError('Hosted demo provisioning already completed for different logins')
        # Do not inspect/reset passwords, activate removed accounts, or replace
        # a reviewer deliberately removed/reassigned since initial provisioning.
        return True
    owner_password, operator_password, auditor_password = _secrets(environ)
    conflicts = database.query('MATCH(m:Member) WHERE m.login IN $names RETURN m.id',
                               {'names':[operator_login,auditor_login]})
    if conflicts:
        raise ProvisioningError('Hosted demo login conflicts with existing members; no accounts were changed')
    current_reviewer = database.query(
        'MATCH(d:Department {id:"finance"}) OPTIONAL MATCH(p:Policy {id:d.current_policy_id}) '
        'RETURN p.reviewer_id')
    if any(row[0] for row in current_reviewer):
        raise ProvisioningError('Finance already has an assigned reviewer; no accounts were changed')
    members = database.query('MATCH(m:Member) RETURN m.id,m.role,m.active,m.workspace_id')
    if members and not any(role=='admin' and active and workspace=='meridian'
                           for _,role,active,workspace in members):
        raise ProvisioningError('Existing storage needs an active administrator before hosted demo provisioning')
    auth = AuthService(database)
    # Creating the demo users first would suppress AuthService's first-owner
    # bootstrap. Keep the existing owner and every existing identity unchanged.
    auth.bootstrap_admin(owner_login,owner_password)
    administrators = database.query('MATCH(m:Member {role:"admin",active:true,workspace_id:"meridian"}) RETURN m.id ORDER BY m.id')
    if not administrators:
        raise ProvisioningError('Workspace administrator bootstrap did not complete')
    attempt = uuid4().hex
    claimed = database.query(
        'MERGE(m:HostedDemoBootstrap {id:$id}) ON CREATE SET m.status="started", '
        'm.attempt=$attempt,m.workspace_id="meridian",m.owner_login=$owner,m.operator_login=$operator, '
        'm.auditor_login=$auditor,m.owner_id=$owner_id '
        'WITH m WHERE m.attempt=$attempt AND m.status="started" RETURN m.id',
        {'id':MARKER_ID,'attempt':attempt,'owner':owner_login,'operator':operator_login,
         'auditor':auditor_login,'owner_id':administrators[0][0]})
    if not claimed:
        raise ProvisioningError('Hosted demo provisioning was already started; local administrator review is required')
    try:
        operator = auth.create_member(operator_login,operator_password,'Demo operator','operator',['general'])
        auditor = auth.create_member(auditor_login,auditor_password,'Demo Finance auditor','finance_auditor',['finance'])
        policy_id = auth.assign_finance_reviewer(auditor.id)
        completed = database.query('MATCH(m:HostedDemoBootstrap {id:$id,attempt:$attempt,status:"started"}) '
            'SET m.status="completed",m.operator_id=$operator,m.auditor_id=$auditor,m.policy_id=$policy RETURN m.id',
            {'id':MARKER_ID,'attempt':attempt,'operator':operator.id,'auditor':auditor.id,'policy':policy_id})
        if not completed:
            raise ProvisioningError('Hosted demo provisioning did not complete')
    except Exception:
        raise ProvisioningError('Hosted demo provisioning is partial; local administrator review is required') from None
    return True


def main(argv=None, *, database=None, environ=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph',help='Graph name; defaults to the configured workspace')
    parser.add_argument('--quiesced',action='store_true',help='Assert HTTP/executor writers are stopped')
    args = parser.parse_args(argv)
    try:
        environment = os.environ if environ is None else environ
        # Disabled is a strict no-op, including avoiding database construction.
        if not _enabled(environment):
            print('Hosted demo provisioning disabled')
            return 0
        target = database if database is not None else GraphDatabase(args.graph)
        enabled = provision(target,environment,quiesced=args.quiesced)
        print('Hosted demo provisioning complete' if enabled else 'Hosted demo provisioning disabled')
        return 0
    except ProvisioningError as exc:
        print(str(exc),file=sys.stderr)
        return 1
    except Exception:
        print('Hosted demo provisioning failed; inspect storage offline',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
