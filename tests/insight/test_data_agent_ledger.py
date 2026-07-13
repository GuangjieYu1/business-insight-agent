from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import flask

from data_formulator.insight.background_runs import list_agent_runs
from data_formulator.insight.data_agent_ledger import (
    DATA_AGENT_LEDGER_KIND,
    DataAgentRunLedger,
    recover_interrupted_data_agent_runs,
)
from data_formulator.insight.domain import AgentRun
from data_formulator.insight.domain.models import new_id, utc_now
from data_formulator.insight.storage import LocalInsightStore, RunStore


def test_ledger_resumes_same_run_and_never_copies_event_bodies(tmp_path):
    store = LocalInsightStore(tmp_path / 'workspace')
    trajectory = [
        {
            'role': 'assistant',
            'content': 'raw-customer-value-must-not-be-stored',
        }
    ]
    ledger = DataAgentRunLedger.start_or_resume(
        store,
        workspace_id='workspace_001',
        input_tables=[{'name': 'sales', 'rows': [{'secret': 'row-secret'}]}],
        user_question='Why did revenue change?',
        resume_trajectory=None,
    )
    first_run_id = ledger.run.id
    assert ledger.run.goal_id is None
    assert ledger.run.execution_kind == DATA_AGENT_LEDGER_KIND
    assert ledger.run.source_table_refs == ['sales']

    ledger.observe(
        {
            'type': 'tool_start',
            'tool': 'explore',
            'code': 'print(raw-customer-value-must-not-be-stored)',
            'purpose': 'inspect row-secret',
        }
    )
    ledger.observe(
        {
            'type': 'tool_result',
            'tool': 'explore',
            'status': 'ok',
            'stdout': 'raw-customer-value-must-not-be-stored',
        }
    )
    ledger.observe(
        {
            'type': 'clarify',
            'questions': [{'text': 'raw-customer-value-must-not-be-stored'}],
            'trajectory': trajectory,
        }
    )

    waiting = RunStore(store, workspace_id='workspace_001').require(first_run_id)
    assert waiting.status == 'waiting_user_input'
    assert waiting.resume_cursor_hash

    resumed = DataAgentRunLedger.start_or_resume(
        store,
        workspace_id='workspace_001',
        input_tables=[{'name': 'sales', 'rows': [{'secret': 'another-secret'}]}],
        user_question='Continue',
        resume_trajectory=trajectory,
    )
    assert resumed.run.id == first_run_id
    resumed.observe(
        {
            'type': 'completion',
            'content': {
                'summary': 'raw-customer-value-must-not-be-stored',
            },
        }
    )

    run_store = RunStore(store, workspace_id='workspace_001')
    assert len(run_store.list()) == 1
    assert run_store.require(first_run_id).status == 'completed'
    persisted_steps = json.dumps(
        [
            step.model_dump(mode='json')
            for step in run_store.list_steps(first_run_id)
        ],
        ensure_ascii=False,
    )
    assert 'raw-customer-value-must-not-be-stored' not in persisted_steps
    assert 'row-secret' not in persisted_steps
    assert 'print(' not in persisted_steps
    assert 'question_hash' in persisted_steps
    assert 'tool_name' in persisted_steps


def test_recovery_marks_only_orphaned_ledger_runs_interrupted(tmp_path):
    store = LocalInsightStore(tmp_path / 'workspace')
    run_store = RunStore(store, workspace_id='workspace_001')
    now = utc_now()
    orphaned = AgentRun(
        id=new_id('run'),
        workspace_id='workspace_001',
        execution_kind=DATA_AGENT_LEDGER_KIND,
        status='analyzing',
        current_stage='analyzing',
        started_at=now,
    )
    legacy = AgentRun(
        id=new_id('run'),
        workspace_id='workspace_001',
        status='analyzing',
        current_stage='analyzing',
        started_at=now,
    )
    run_store.create(orphaned)
    run_store.create(legacy)

    recovered = recover_interrupted_data_agent_runs(
        store,
        workspace_id='workspace_001',
    )

    assert [run.id for run in recovered] == [orphaned.id]
    interrupted = run_store.require(orphaned.id)
    assert interrupted.status == 'interrupted'
    assert interrupted.interrupted_at is not None
    assert run_store.require(legacy.id).status == 'analyzing'
    events = [
        step.detail.get('event_type')
        for step in run_store.list_steps(orphaned.id)
    ]
    assert events == ['run_interrupted']


def test_table_name_filter_uses_ledger_source_refs(tmp_path):
    store = LocalInsightStore(tmp_path / 'workspace')
    run_store = RunStore(store, workspace_id='workspace_001')
    run_store.create(
        AgentRun(
            id=new_id('run'),
            workspace_id='workspace_001',
            execution_kind=DATA_AGENT_LEDGER_KIND,
            source_table_refs=['sales'],
        )
    )
    run_store.create(
        AgentRun(
            id=new_id('run'),
            workspace_id='workspace_001',
            execution_kind=DATA_AGENT_LEDGER_KIND,
            source_table_refs=['inventory'],
        )
    )

    runs = list_agent_runs(
        store,
        workspace_id='workspace_001',
        table_name='sales',
    )

    assert len(runs) == 1
    assert runs[0].source_table_refs == ['sales']


def test_ledger_failure_does_not_change_data_agent_stream():
    from data_formulator.routes.agents import agent_bp

    app = flask.Flask(__name__)
    app.config['TESTING'] = True
    app.config['CLI_ARGS'] = {'product_mode': 'business_insight'}
    app.register_blueprint(agent_bp)
    client = app.test_client()

    agent_instance = MagicMock()
    agent_instance.run.return_value = [
        {'type': 'text_delta', 'content': 'hello'},
        {'type': 'completion', 'content': {'summary': 'done'}},
    ]
    broken_ledger = MagicMock()
    broken_ledger.observe.side_effect = OSError('ledger unavailable')

    with (
        patch(
            'data_formulator.routes.agents.get_identity_id',
            return_value='user-1',
        ),
        patch(
            'data_formulator.routes.agents.get_client',
            return_value=object(),
        ),
        patch(
            'data_formulator.routes.agents.get_workspace',
            return_value=object(),
        ),
        patch(
            'data_formulator.routes.agents.DataAgent',
            return_value=agent_instance,
        ),
        patch(
            'data_formulator.routes.agents._start_data_agent_ledger',
            return_value=broken_ledger,
        ),
    ):
        response = client.post(
            '/api/agent/data-agent-streaming',
            json={
                'model': {},
                'input_tables': [],
                'user_question': 'what changed?',
            },
        )

    expected = (
        json.dumps(
            {'type': 'text_delta', 'content': 'hello'},
            ensure_ascii=False,
        )
        + '\n'
        + json.dumps(
            {'type': 'completion', 'content': {'summary': 'done'}},
            ensure_ascii=False,
        )
        + '\n'
    ).encode('utf-8')
    assert response.data == expected
