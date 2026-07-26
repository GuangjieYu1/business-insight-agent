from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import flask

from data_formulator.routes.agents import agent_bp
from data_formulator.sandbox.runtime_packages import MissingRuntimePackage


def test_explicit_package_request_returns_approval_without_starting_data_agent():
    app = flask.Flask(__name__)
    app.config['TESTING'] = True
    app.config['CLI_ARGS'] = {'product_mode': 'business_insight'}
    app.register_blueprint(agent_bp)
    client = app.test_client()

    workspace = MagicMock()
    workspace.confined_root.root.name = 'workspace_001'
    ledger = MagicMock()
    ledger.observe.return_value = ledger

    with (
        patch('data_formulator.routes.agents.get_identity_id', return_value='user_001'),
        patch('data_formulator.routes.agents.get_client', return_value=object()),
        patch('data_formulator.routes.agents.get_workspace', return_value=workspace),
        patch('data_formulator.routes.agents.runtime_install_enabled', return_value=True),
        patch(
            'data_formulator.sandbox.runtime_packages.detect_explicit_runtime_package_requests',
            return_value=[MissingRuntimePackage('xgboost', 'xgboost')],
        ),
        patch('data_formulator.routes.agents._start_data_agent_ledger', return_value=ledger),
        patch('data_formulator.routes.agents._call_data_agent_ledger', return_value=ledger),
        patch('data_formulator.routes.agents.DataAgent') as data_agent,
    ):
        response = client.post(
            '/api/agent/data-agent-streaming',
            json={
                'model': {},
                'input_tables': [],
                'user_question': '下载xgboost进行分析',
            },
        )

    assert response.status_code == 200
    event = json.loads(response.data.decode('utf-8').strip())
    assert event['type'] == 'approval_required'
    assert event['packages'] == ['xgboost']
    assert event['missing_imports'] == ['xgboost']
    assert event['trajectory'] == [{'role': 'user', 'content': '下载xgboost进行分析'}]
    data_agent.assert_not_called()
    ledger.observe.assert_not_called()
