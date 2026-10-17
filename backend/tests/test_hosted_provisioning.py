"""Offline opt-in provisioning never changes an existing identity or grant."""
import importlib.util
from functools import cache
from pathlib import Path

import pytest

from relay.auth import AuthError, AuthService
from relay.migrations import MIGRATION_CHECKSUM

pytest_plugins = ['identity_helpers']


@cache
def module():
    path = Path(__file__).resolve().parents[2]/'scripts'/'provision_hosted.py'
    assert path.is_file(), 'hosted offline provisioner is missing'
    spec = importlib.util.spec_from_file_location('provision_hosted',path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def configuration():
    return {'RELAY_PROVISION_DEMO_ACCOUNTS':'1',
            'RELAY_ACCESS_PASSWORD':'owner test secret 4321',
            'RELAY_OPERATOR_PASSWORD':'operator test secret 7654',
            'RELAY_FINANCE_AUDITOR_PASSWORD':'auditor test secret 9876'}


@pytest.fixture
def ready_db(identity_db):
    identity_db.query('CREATE (:Workspace {id:"meridian",schema_version:1,maintenance:false}), '
                      '(:SchemaMigration {id:"001_workflows",status:"complete",version:1,checksum:$checksum})',
                      {'checksum':MIGRATION_CHECKSUM})
    return identity_db


def snapshot(database):
    return database.query('MATCH (n) RETURN labels(n),properties(n) ORDER BY n.id')


def test_default_disabled_is_read_only_and_strict_flags_reject_without_writes(ready_db):
    before = snapshot(ready_db)
    assert module().provision(ready_db,{}) is False
    for flag in ('true','yes','', '01'):
        with pytest.raises(module().ProvisioningError):
            module().provision(ready_db,{'RELAY_PROVISION_DEMO_ACCOUNTS':flag},quiesced=True)
    assert snapshot(ready_db)==before


def test_fresh_provision_creates_owner_first_and_separate_successful_demo_logins(ready_db):
    env = configuration()
    assert module().provision(ready_db,env,quiesced=True)
    auth = AuthService(ready_db)
    owner = auth.login('owner',env['RELAY_ACCESS_PASSWORD']).view.member
    operator = auth.login('demo-operator',env['RELAY_OPERATOR_PASSWORD']).view.member
    auditor = auth.login('demo-auditor',env['RELAY_FINANCE_AUDITOR_PASSWORD']).view.member
    assert owner.role=='admin' and operator.role=='operator' and auditor.role=='finance_auditor'
    assert len({owner.id,operator.id,auditor.id})==3
    assert ready_db.query('MATCH(d:Department {id:"finance"})-[:GOVERNED_BY]->(p:Policy) WHERE p.id=d.current_policy_id RETURN p.reviewer_id')==[[auditor.id]]
    assert ready_db.query('MATCH(m:Member {id:$id})-[:MEMBER_OF]->(:Department {id:"finance"}) RETURN count(m)',{'id':auditor.id})==[[1]]
    assert ready_db.query('MATCH(m:HostedDemoBootstrap {id:"meridian:1"}) RETURN m.status')==[['completed']]


def test_completed_marker_preserves_passwords_disable_and_changed_finance_reviewer(ready_db):
    env = configuration()
    module().provision(ready_db,env,quiesced=True)
    auth = AuthService(ready_db)
    auditor = auth.login('demo-auditor',env['RELAY_FINANCE_AUDITOR_PASSWORD']).view.member
    auth.update_member(auditor.id,active=False)
    replacement = auth.create_member('replacement','replacement test secret','Replacement','finance_auditor',['finance'])
    auth.assign_finance_reviewer(replacement.id)
    before = snapshot(ready_db)
    changed = {**env,'RELAY_ACCESS_PASSWORD':'different owner secret',
               'RELAY_OPERATOR_PASSWORD':'different operator secret',
               'RELAY_FINANCE_AUDITOR_PASSWORD':'different auditor secret'}
    assert module().provision(ready_db,changed,quiesced=True)
    assert snapshot(ready_db)==before
    assert auth.login('demo-operator',env['RELAY_OPERATOR_PASSWORD']).view.member.role=='operator'
    with pytest.raises(AuthError):
        auth.login('demo-operator',changed['RELAY_OPERATOR_PASSWORD'])
    with pytest.raises(AuthError):
        auth.login('demo-auditor',env['RELAY_FINANCE_AUDITOR_PASSWORD'])


@pytest.mark.parametrize('change',[{'RELAY_OPERATOR_PASSWORD':''}, {'RELAY_FINANCE_AUDITOR_PASSWORD':'short'},
    {'RELAY_FINANCE_AUDITOR_PASSWORD':'operator test secret 7654'}, {'RELAY_OPERATOR_LOGIN':'owner'},
    {'RELAY_FINANCE_AUDITOR_LOGIN':'DEMO-OPERATOR'}, {'RELAY_ACCESS_PASSWORD':''},
    {'RELAY_OPERATOR_LOGIN':'invalid login'}])
def test_invalid_initial_config_and_unquiesced_setup_do_not_mutate(ready_db,change):
    before = snapshot(ready_db)
    with pytest.raises(module().ProvisioningError):
        module().provision(ready_db,{**configuration(),**change},quiesced=True)
    assert snapshot(ready_db)==before
    with pytest.raises(module().ProvisioningError):
        module().provision(ready_db,configuration())
    assert snapshot(ready_db)==before


def test_existing_login_or_assigned_reviewer_conflict_does_not_mutate(ready_db):
    auth = AuthService(ready_db)
    auth.create_member('demo-operator','preexisting test secret','Existing','operator')
    before = snapshot(ready_db)
    with pytest.raises(module().ProvisioningError):
        module().provision(ready_db,configuration(),quiesced=True)
    assert snapshot(ready_db)==before


def test_partial_marker_blocks_restart_without_reset_or_new_assignment(ready_db):
    ready_db.query('CREATE (:HostedDemoBootstrap {id:"meridian:1",status:"started"})')
    before = snapshot(ready_db)
    with pytest.raises(module().ProvisioningError):
        module().provision(ready_db,configuration(),quiesced=True)
    assert snapshot(ready_db)==before


def test_existing_unrelated_admin_and_data_are_retained(ready_db):
    auth = AuthService(ready_db)
    admin = auth.create_member('existing-admin','existing admin secret','Administrator','admin')
    ready_db.query('CREATE (:Source {id:"keep",payload:"original"})')
    module().provision(ready_db,configuration(),quiesced=True)
    assert auth.login('existing-admin','existing admin secret').view.member.id==admin.id
    assert ready_db.query('MATCH(s:Source {id:"keep"}) RETURN s.payload')==[['original']]
    assert ready_db.query('MATCH(m:Member {login:"owner"}) RETURN count(m)')==[[0]]


def test_preassigned_finance_reviewer_is_not_replaced(ready_db):
    auth = AuthService(ready_db)
    auth.create_member('existing-admin','existing admin secret','Administrator','admin')
    auditor = auth.create_member('existing-auditor','existing auditor secret','Auditor','finance_auditor',['finance'])
    auth.assign_finance_reviewer(auditor.id)
    before = snapshot(ready_db)
    with pytest.raises(module().ProvisioningError):
        module().provision(ready_db,configuration(),quiesced=True)
    assert snapshot(ready_db)==before


def test_cli_sanitizes_partial_failure_and_restart_does_not_retry_changes(ready_db,monkeypatch,capsys):
    cli = module()
    def unavailable(self,member_id):
        raise RuntimeError('private test-only diagnostic that must not be printed')
    monkeypatch.setattr(cli.AuthService,'assign_finance_reviewer',unavailable)
    assert cli.main(['--quiesced'],database=ready_db,environ=configuration())==1
    rendered = capsys.readouterr()
    assert 'private test-only' not in rendered.err
    assert 'partial' in rendered.err
    assert ready_db.query('MATCH(m:HostedDemoBootstrap {id:"meridian:1"}) RETURN m.status')==[['started']]
    before = snapshot(ready_db)
    assert cli.main(['--quiesced'],database=ready_db,environ=configuration())==1
    assert snapshot(ready_db)==before


def test_schema_not_ready_is_read_only_and_completed_provisioning_ignores_missing_passwords(ready_db):
    ready_db.query('MATCH(w:Workspace {id:"meridian"}) SET w.maintenance=true')
    before = snapshot(ready_db)
    with pytest.raises(module().ProvisioningError):
        module().provision(ready_db,configuration(),quiesced=True)
    assert snapshot(ready_db)==before
    ready_db.query('MATCH(w:Workspace {id:"meridian"}) SET w.maintenance=false')
    module().provision(ready_db,configuration(),quiesced=True)
    before = snapshot(ready_db)
    assert module().provision(ready_db,{'RELAY_PROVISION_DEMO_ACCOUNTS':'1'},quiesced=True)
    assert snapshot(ready_db)==before


def test_standalone_cli_help_resolves_package_without_pythonpath(tmp_path):
    import subprocess
    import sys
    path = Path(__file__).resolve().parents[2]/'scripts'/'provision_hosted.py'
    result = subprocess.run([sys.executable,str(path),'--help'],cwd=tmp_path,
                            env={'LANG':'C.UTF-8'},capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert '--quiesced' in result.stdout
    assert not result.stderr


@pytest.mark.parametrize('flag,expected',[('0',0),('true',1)])
def test_disabled_or_malformed_cli_flag_does_not_construct_database(monkeypatch,capsys,flag,expected):
    cli = module()
    calls = []
    def forbidden(*args,**kwargs):
        calls.append(True)
        raise AssertionError('A disabled provisioner must not construct a database')
    monkeypatch.setattr(cli,'GraphDatabase',forbidden)
    assert cli.main([],environ={'RELAY_PROVISION_DEMO_ACCOUNTS':flag})==expected
    assert not calls
    rendered = capsys.readouterr()
    assert 'Traceback' not in rendered.err
