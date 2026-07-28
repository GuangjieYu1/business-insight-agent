from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from data_formulator.sandbox.local_sandbox import LocalSandbox
from data_formulator.sandbox.runtime_packages import (
    _APPROVALS,
    classify_sandbox_violation,
    consume_runtime_package_approval,
    create_runtime_package_approval,
    detect_missing_runtime_packages,
    RuntimePackageInstallResult,
    _AttemptResult,
    _InstallerCommand,
    _append_manifest_entry,
    _install_from_source,
    _select_installer,
    install_runtime_packages,
    manifest_import_names,
    normalize_package_name,
    runtime_bundle_paths,
)


def test_detects_multiple_missing_imports_as_one_request(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_FORMULATOR_HOME", str(tmp_path))

    def fake_find_spec(name):
        if name in {"xgboost", "shap"}:
            return None
        return object()

    monkeypatch.setattr("importlib.util.find_spec", fake_find_spec)

    missing = detect_missing_runtime_packages("import xgboost\nimport shap\nimport pandas as pd")

    assert [item.import_name for item in missing] == ["shap", "xgboost"]
    assert [item.package_name for item in missing] == ["shap", "xgboost"]


@pytest.mark.parametrize(
    "raw",
    [
        "https://example.com/pkg.whl",
        "git+https://example.com/repo",
        "xgboost --extra-index-url evil",
        "../xgboost",
        "",
    ],
)
def test_rejects_non_pypi_package_names(raw):
    with pytest.raises(ValueError):
        normalize_package_name(raw)


def test_runtime_approval_is_bound_to_user_workspace_and_single_use(tmp_path):
    approval = create_runtime_package_approval(
        identity_id="user-a",
        workspace_id="workspace-a",
        packages=["xgboost"],
        import_names=["xgboost"],
        trajectory=[{"role": "user", "content": "safe"}],
        completed_step_count=2,
    )

    with pytest.raises(ValueError):
        consume_runtime_package_approval(
            identity_id="user-b",
            workspace_id="workspace-a",
            approval_id=approval.id,
            decision="approve",
        )

    consumed = consume_runtime_package_approval(
        identity_id="user-a",
        workspace_id="workspace-a",
        approval_id=approval.id,
        decision="reject",
    )
    assert consumed.status == "rejected"
    assert consumed.completed_step_count == 2

    with pytest.raises(ValueError):
        consume_runtime_package_approval(
            identity_id="user-a",
            workspace_id="workspace-a",
            approval_id=approval.id,
            decision="approve",
        )


def test_runtime_approval_expires(tmp_path):
    approval = create_runtime_package_approval(
        identity_id="user-a",
        workspace_id="workspace-a",
        packages=["shap"],
        import_names=["shap"],
        trajectory=[],
        completed_step_count=0,
    )
    _APPROVALS[approval.id].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    with pytest.raises(ValueError):
        consume_runtime_package_approval(
            identity_id="user-a",
            workspace_id="workspace-a",
            approval_id=approval.id,
            decision="approve",
        )


def test_local_sandbox_static_missing_import_pauses_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_RUNTIME_PACKAGE_INSTALL", "true")
    monkeypatch.setenv("DATA_FORMULATOR_HOME", str(tmp_path))

    result = LocalSandbox._run_in_warm_subprocess(
        "import bia_missing_package_for_test\n_pack = {'stdout': ''}",
        {"_pack": None},
        str(tmp_path),
    )

    assert result["status"] == "approval_required"
    assert result["missing_imports"] == ["bia_missing_package_for_test"]


def test_local_sandbox_dynamic_missing_import_is_structured(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_RUNTIME_PACKAGE_INSTALL", "true")
    monkeypatch.setenv("DATA_FORMULATOR_HOME", str(tmp_path))

    result = LocalSandbox._run_in_warm_subprocess(
        "__import__('bia_missing_dynamic_for_test')\n_pack = {'stdout': ''}",
        {"_pack": None},
        str(tmp_path),
    )

    assert result["status"] == "error"
    assert result["missing_imports"] == ["bia_missing_dynamic_for_test"]


def test_non_package_sandbox_violations_are_not_approvable():
    violation = classify_sandbox_violation("Error: OSError - network access forbidden in sandbox")

    assert violation == {
        "category": "network_access",
        "message": "Sandbox blocked network access. This cannot be approved from the analysis UI.",
    }




def test_selects_current_python_pip_when_available(monkeypatch):
    class Completed:
        returncode = 0

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return Completed()

    monkeypatch.setattr('data_formulator.sandbox.runtime_packages.subprocess.run', fake_run)

    installer = _select_installer()

    assert installer is not None
    assert installer.kind == 'pip'
    assert installer.prefix[-2:] == ['-m', 'pip'] or installer.prefix[-3:] == ['-m', 'pip', 'install']
    assert calls[0][-2:] == ['pip', '--version']


def test_selects_uv_when_current_python_has_no_pip(monkeypatch):
    class Completed:
        returncode = 1

    monkeypatch.setattr('data_formulator.sandbox.runtime_packages.subprocess.run', lambda *args, **kwargs: Completed())
    monkeypatch.setattr('data_formulator.sandbox.runtime_packages.shutil.which', lambda name: '/usr/bin/uv' if name == 'uv' else None)

    installer = _select_installer()

    assert installer is not None
    assert installer.kind == 'uv'
    assert installer.prefix[:3] == ['/usr/bin/uv', 'pip', 'install']
    assert '--python' in installer.prefix


def test_reports_no_installer_when_pip_and_uv_are_unavailable(monkeypatch):
    class Completed:
        returncode = 1

    monkeypatch.setattr('data_formulator.sandbox.runtime_packages.subprocess.run', lambda *args, **kwargs: Completed())
    monkeypatch.setattr('data_formulator.sandbox.runtime_packages.shutil.which', lambda name: None)

    assert _select_installer() is None


def test_install_uses_secondary_after_primary_source_failure(monkeypatch, tmp_path):
    monkeypatch.setenv('ENABLE_RUNTIME_PACKAGE_INSTALL', 'true')
    monkeypatch.setenv('DATA_FORMULATOR_HOME', str(tmp_path))
    monkeypatch.setattr('data_formulator.sandbox.runtime_packages._select_installer', lambda timeout_seconds=10: _InstallerCommand('pip', ['python', '-m', 'pip', 'install']))
    monkeypatch.setattr('data_formulator.sandbox.runtime_packages._module_available', lambda name: False)
    attempts = []

    def fake_attempt(**kwargs):
        attempts.append(kwargs['source_id'])
        if kwargs['source_id'] == 'primary':
            return _AttemptResult(False, True, 'temporary failure in name resolution', 'source_unreachable', {'id': 'primary'})
        return _AttemptResult(True, False, source={'id': 'secondary', 'label': 'Tsinghua PyPI mirror', 'domain': 'mirrors.tuna.tsinghua.edu.cn'}, versions={'xgboost': '1.2.3'})

    monkeypatch.setattr('data_formulator.sandbox.runtime_packages._install_from_source', fake_attempt)

    result = install_runtime_packages(packages=['xgboost'], import_names=['xgboost'])

    assert result.ok is True
    assert result.status == 'installed'
    assert result.source and result.source['id'] == 'secondary'
    assert attempts == ['primary', 'secondary']
    assert [event['status'] for event in result.progress_events] == ['installing', 'retrying_secondary']


def test_domestic_source_failures_request_official_approval(monkeypatch, tmp_path):
    monkeypatch.setenv('ENABLE_RUNTIME_PACKAGE_INSTALL', 'true')
    monkeypatch.setenv('DATA_FORMULATOR_HOME', str(tmp_path))
    monkeypatch.setattr('data_formulator.sandbox.runtime_packages._select_installer', lambda timeout_seconds=10: _InstallerCommand('pip', ['python', '-m', 'pip', 'install']))
    monkeypatch.setattr('data_formulator.sandbox.runtime_packages._module_available', lambda name: False)
    monkeypatch.setattr(
        'data_formulator.sandbox.runtime_packages._install_from_source',
        lambda **kwargs: _AttemptResult(False, True, 'read timed out', 'install_timeout', {'id': kwargs['source_id']}),
    )

    result = install_runtime_packages(packages=['shap'], import_names=['shap'])

    assert result.ok is False
    assert result.status == 'awaiting_official_approval'
    assert result.error_code == 'install_timeout'
    assert [event['status'] for event in result.progress_events] == ['installing', 'retrying_secondary']


def test_local_install_errors_do_not_request_official_approval(monkeypatch, tmp_path):
    monkeypatch.setenv('ENABLE_RUNTIME_PACKAGE_INSTALL', 'true')
    monkeypatch.setenv('DATA_FORMULATOR_HOME', str(tmp_path))
    monkeypatch.setattr('data_formulator.sandbox.runtime_packages._select_installer', lambda timeout_seconds=10: _InstallerCommand('pip', ['python', '-m', 'pip', 'install']))
    monkeypatch.setattr('data_formulator.sandbox.runtime_packages._module_available', lambda name: False)
    monkeypatch.setattr(
        'data_formulator.sandbox.runtime_packages._install_from_source',
        lambda **kwargs: _AttemptResult(False, False, 'No matching distribution found for shap', 'no_compatible_wheel', {'id': kwargs['source_id']}),
    )

    result = install_runtime_packages(packages=['shap'], import_names=['shap'])

    assert result.ok is False
    assert result.status == 'failed'
    assert result.error_code == 'no_compatible_wheel'
    assert [event['status'] for event in result.progress_events] == ['installing']


def test_install_command_uses_binary_wheels_and_shell_false(monkeypatch, tmp_path):
    monkeypatch.setenv('DATA_FORMULATOR_HOME', str(tmp_path))
    captured = {}

    class Completed:
        returncode = 0
        stdout = ''
        stderr = ''

    def fake_run(cmd, **kwargs):
        captured['cmd'] = cmd
        captured['shell'] = kwargs.get('shell')
        target = cmd[cmd.index('--target') + 1]
        Path(target).mkdir(parents=True, exist_ok=True)
        return Completed()

    monkeypatch.setattr('data_formulator.sandbox.runtime_packages.subprocess.run', fake_run)
    monkeypatch.setattr(
        'data_formulator.sandbox.runtime_packages._verify_installed_bundle',
        lambda staging_dir, import_names, packages: _AttemptResult(True, versions={'xgboost': '1.2.3'}),
    )

    result = _install_from_source(
        installer=_InstallerCommand('pip', ['python', '-m', 'pip', 'install']),
        packages=['xgboost'],
        import_names=['xgboost'],
        source_id='primary',
        timeout_seconds=30,
    )

    assert result.ok is True
    assert captured['shell'] is False
    assert '--only-binary=:all:' in captured['cmd']
    assert '--target' in captured['cmd']
    assert 'xgboost' in captured['cmd']


def test_manifest_uses_abi_bundle_paths_and_legacy_manifest(monkeypatch, tmp_path):
    monkeypatch.setenv('DATA_FORMULATOR_HOME', str(tmp_path))
    runtime_root = tmp_path / 'runtime-python'
    bundle = runtime_root / 'cpython-test-x86_64' / 'bundles' / 'bundle-1'
    bundle.mkdir(parents=True)
    monkeypatch.setattr('data_formulator.sandbox.runtime_packages.get_runtime_package_dir', lambda: runtime_root / 'cpython-test-x86_64')

    _append_manifest_entry({
        'bundle': 'bundle-1',
        'packages': ['xgboost'],
        'import_names': ['xgboost'],
        'versions': {'xgboost': '1.2.3'},
        'source_id': 'primary',
    })
    (runtime_root / '_manifest.json').write_text(
        '{"schema_version":"1.0","packages":{"shap":{"import_names":["shap"]}}}',
        encoding='utf-8',
    )

    assert runtime_bundle_paths() == [str(bundle.resolve())]
    assert manifest_import_names() == ['shap', 'xgboost']
