'''Privacy-minimized task ledger for the existing Data Agent stream.

This module observes stream events without changing the Data Agent request,
response, prompt, tools, or control flow. Callers must treat every ledger
operation as best effort so persistence can never break the original agent.
'''

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import re
from threading import Lock
from typing import Any

from data_formulator.insight.domain import AgentRun, AgentStep
from data_formulator.insight.domain.models import new_id, utc_now
from data_formulator.insight.registry import list_datasets, read_dataset_version
from data_formulator.insight.storage import InsightStore, RunStore


DATA_AGENT_LEDGER_KIND = 'data_agent_ledger'
_ACTIVE_RUN_IDS: set[str] = set()
_ACTIVE_RUN_IDS_LOCK = Lock()
_SAFE_METADATA_TOKEN = re.compile(r'[^A-Za-z0-9_.:-]+')


def trajectory_hash(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        default=str,
    )
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def _resume_cursor_hash(
    *,
    resume_trajectory: list[dict[str, Any]] | None,
    resume_token: str | None,
) -> str | None:
    if resume_trajectory is not None:
        return trajectory_hash(resume_trajectory)
    if isinstance(resume_token, str) and resume_token.strip():
        return trajectory_hash({'resume_token': resume_token.strip()})
    return None


def _question_title(question: str, *, limit: int = 120) -> str:
    normalized = ' '.join(str(question or '').split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + '...'


def _safe_token(value: Any, *, fallback: str = 'unknown') -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = _SAFE_METADATA_TOKEN.sub('_', value.strip())[:80].strip('_')
    return cleaned or fallback


def _table_refs(input_tables: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for table in input_tables:
        if not isinstance(table, dict):
            continue
        name = table.get('name')
        if isinstance(name, str) and name.strip() and name.strip() not in refs:
            refs.append(name.strip())
    return refs


def _resolve_dataset_binding(
    store: InsightStore,
    *,
    workspace_id: str,
    table_refs: list[str],
) -> tuple[str | None, str | None]:
    ref_set = set(table_refs)
    matches = [
        dataset
        for dataset in list_datasets(store)
        if dataset.workspace_id == workspace_id
        and (dataset.original_table_ref in ref_set or dataset.name in ref_set)
    ]
    if len(matches) != 1:
        return None, None
    dataset = matches[0]
    version = read_dataset_version(store, dataset.id, dataset.active_version_id)
    if version is None or version.workspace_id != workspace_id:
        return dataset.id, None
    return dataset.id, version.id


def _mark_active(run_id: str) -> None:
    with _ACTIVE_RUN_IDS_LOCK:
        _ACTIVE_RUN_IDS.add(run_id)


def _mark_inactive(run_id: str) -> None:
    with _ACTIVE_RUN_IDS_LOCK:
        _ACTIVE_RUN_IDS.discard(run_id)


def recover_interrupted_data_agent_runs(
    store: InsightStore,
    *,
    workspace_id: str,
) -> list[AgentRun]:
    '''Mark ledger Runs left active by a previous server process interrupted.'''

    run_store = RunStore(store, workspace_id=workspace_id)
    recovered: list[AgentRun] = []
    for run in run_store.list():
        with _ACTIVE_RUN_IDS_LOCK:
            is_active = run.id in _ACTIVE_RUN_IDS
        if (
            run.execution_kind != DATA_AGENT_LEDGER_KIND
            or run.status not in {'created', 'analyzing'}
            or is_active
        ):
            continue
        now = utc_now()
        updated = run.model_copy(
            update={
                'status': 'interrupted',
                'current_stage': 'interrupted',
                'interrupted_at': now,
                'completed_at': now,
                'updated_at': now,
            }
        )
        run_store.update(updated)
        run_store.append_step(
            AgentStep(
                id=new_id('step'),
                workspace_id=workspace_id,
                run_id=run.id,
                type='error',
                title='Data Agent task interrupted',
                status='failed',
                started_at=now,
                completed_at=now,
                progress_text='The server stopped before this task reached a terminal event.',
                detail={
                    'event_type': 'run_interrupted',
                    'stage': 'interrupted',
                    'error_code': 'SERVER_PROCESS_INTERRUPTED',
                },
            )
        )
        recovered.append(updated)
    return recovered


@dataclass
class DataAgentRunLedger:
    store: InsightStore
    workspace_id: str
    run_store: RunStore
    run: AgentRun
    dataset_id: str | None = None
    _closed: bool = False
    _saw_error: bool = False
    _tool_started_at: dict[str, list[datetime]] = field(default_factory=dict)

    @classmethod
    def start_or_resume(
        cls,
        store: InsightStore,
        *,
        workspace_id: str,
        input_tables: list[dict[str, Any]],
        user_question: str,
        resume_trajectory: list[dict[str, Any]] | None,
        resume_token: str | None = None,
    ) -> 'DataAgentRunLedger':
        recover_interrupted_data_agent_runs(store, workspace_id=workspace_id)
        run_store = RunStore(store, workspace_id=workspace_id)

        cursor_hash = _resume_cursor_hash(
            resume_trajectory=resume_trajectory,
            resume_token=resume_token,
        )
        if cursor_hash is not None:
            for existing in reversed(run_store.list()):
                if (
                    existing.execution_kind == DATA_AGENT_LEDGER_KIND
                    and existing.status in {'waiting_user_input', 'waiting_approval'}
                    and existing.resume_cursor_hash == cursor_hash
                ):
                    now = utc_now()
                    _mark_active(existing.id)
                    resume_stage = (
                        'waiting_approval'
                        if existing.status == 'waiting_approval'
                        else 'waiting_user_input'
                    )
                    resumed = existing.model_copy(
                        update={
                            'status': 'analyzing',
                            'current_stage': 'analyzing',
                            'resume_cursor_hash': None,
                            'updated_at': now,
                        }
                    )
                    try:
                        run_store.update(resumed)
                        run_store.append_step(
                            AgentStep(
                                id=new_id('step'),
                                workspace_id=workspace_id,
                                run_id=resumed.id,
                                type='progress',
                                title='Data Agent task resumed',
                                status='completed',
                                started_at=now,
                                completed_at=now,
                                progress_text=(
                                    'The existing Data Agent task resumed after package approval.'
                                    if resume_stage == 'waiting_approval'
                                    else 'The existing Data Agent task resumed after user input.'
                                ),
                                detail={
                                    'event_type': 'step_completed',
                                    'stage': 'analyzing',
                                    'resume_stage': resume_stage,
                                },
                            )
                        )
                    except Exception:
                        _mark_inactive(existing.id)
                        raise
                    return cls(
                        store=store,
                        workspace_id=workspace_id,
                        run_store=run_store,
                        run=resumed,
                    )

        refs = _table_refs(input_tables)
        dataset_id, version_id = _resolve_dataset_binding(
            store,
            workspace_id=workspace_id,
            table_refs=refs,
        )
        now = utc_now()
        run = AgentRun(
            id=new_id('run'),
            workspace_id=workspace_id,
            goal_id=None,
            dataset_version_id=version_id,
            execution_kind=DATA_AGENT_LEDGER_KIND,
            source_table_refs=refs,
            status='analyzing',
            current_stage='analyzing',
            started_at=now,
        )
        _mark_active(run.id)
        try:
            run_store.create(run)
        except Exception:
            _mark_inactive(run.id)
            raise
        question_title = _question_title(user_question)
        detail: dict[str, Any] = {
            'event_type': 'run_started',
            'stage': 'analyzing',
            'question_hash': trajectory_hash(str(user_question or '')),
            'question_title': question_title,
            'source_table_refs': refs,
        }
        if dataset_id is not None:
            detail['dataset_id'] = dataset_id
        if version_id is not None:
            detail['version_id'] = version_id
        try:
            run_store.append_step(
                AgentStep(
                    id=new_id('step'),
                    workspace_id=workspace_id,
                    run_id=run.id,
                    type='progress',
                    title=question_title or 'Data Agent task started',
                    status='completed',
                    started_at=now,
                    completed_at=now,
                    input_refs=refs,
                    progress_text='The existing Data Agent started processing this question.',
                    detail=detail,
                )
            )
        except Exception:
            _mark_inactive(run.id)
            raise
        return cls(
            store=store,
            workspace_id=workspace_id,
            run_store=run_store,
            run=run,
            dataset_id=dataset_id,
        )

    def _append_step(
        self,
        *,
        step_type: str,
        title: str,
        status: str,
        progress_text: str,
        detail: dict[str, Any],
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        now = utc_now()
        self.run_store.append_step(
            AgentStep(
                id=new_id('step'),
                workspace_id=self.workspace_id,
                run_id=self.run.id,
                type=step_type,
                title=title,
                status=status,
                started_at=started_at or now,
                completed_at=completed_at,
                input_refs=list(self.run.source_table_refs),
                progress_text=progress_text,
                detail=detail,
            )
        )

    def _transition(
        self,
        status: str,
        *,
        stage: str,
        resume_cursor_hash: str | None = None,
        interrupted: bool = False,
    ) -> None:
        now = utc_now()
        current = self.run_store.require(self.run.id)
        terminal = status in {'completed', 'failed', 'cancelled', 'interrupted'}
        self.run = current.model_copy(
            update={
                'status': status,
                'current_stage': stage,
                'resume_cursor_hash': resume_cursor_hash,
                'completed_at': now if terminal else None,
                'interrupted_at': now if interrupted else current.interrupted_at,
                'updated_at': now,
            }
        )
        self.run_store.update(self.run)

    def _close(self) -> None:
        self._closed = True
        _mark_inactive(self.run.id)

    def observe(self, event: dict[str, Any]) -> None:
        if self._closed or not isinstance(event, dict):
            return
        event_type = event.get('type')

        if event_type in {'tool_start', 'action'}:
            tool = _safe_token(
                event.get('tool') or event.get('action'),
                fallback='data_agent_tool',
            )
            started = utc_now()
            self._tool_started_at.setdefault(tool, []).append(started)
            self._append_step(
                step_type='tool_call',
                title=f'Run {tool}',
                status='running',
                progress_text='Data Agent started a tool.',
                started_at=started,
                detail={
                    'event_type': 'step_started',
                    'stage': 'analyzing',
                    'tool_name': tool,
                },
            )
            return

        if event_type in {'tool_result', 'result', 'explore_result'}:
            tool = _safe_token(event.get('tool'), fallback='data_agent_tool')
            started_entries = self._tool_started_at.get(tool, [])
            started = started_entries.pop(0) if started_entries else utc_now()
            completed = utc_now()
            tool_status = _safe_token(event.get('status'), fallback='completed')
            failed = tool_status not in {'ok', 'success', 'completed'}
            self._append_step(
                step_type='tool_call',
                title=f'Run {tool}',
                status='failed' if failed else 'completed',
                progress_text=(
                    'Data Agent tool execution failed.'
                    if failed
                    else 'Data Agent completed a tool.'
                ),
                started_at=started,
                completed_at=completed,
                detail={
                    'event_type': 'step_completed',
                    'stage': 'analyzing',
                    'tool_name': tool,
                    'tool_status': tool_status,
                    'duration_ms': max(
                        0,
                        int((completed - started).total_seconds() * 1000),
                    ),
                    **(
                        {'error_code': 'TOOL_EXECUTION_FAILED'}
                        if failed
                        else {}
                    ),
                },
            )
            return

        if event_type in {'clarify', 'explain'}:
            trajectory = event.get('trajectory')
            cursor_hash = _resume_cursor_hash(
                resume_trajectory=trajectory if isinstance(trajectory, list) else None,
                resume_token=None,
            )
            now = utc_now()
            self._transition(
                'waiting_user_input',
                stage='waiting_user_input',
                resume_cursor_hash=cursor_hash,
            )
            self._append_step(
                step_type='observation',
                title='Data Agent is waiting for user input',
                status='completed',
                progress_text='The task is paused until the user continues the existing Data Agent conversation.',
                started_at=now,
                completed_at=now,
                detail={
                    'event_type': 'user_input_required',
                    'stage': 'waiting_user_input',
                    'interaction_type': event_type,
                },
            )
            self._close()
            return

        if event_type == 'approval_required':
            approval = event.get('approval')
            approval_id = (
                approval.get('id')
                if isinstance(approval, dict)
                else None
            )
            cursor_hash = _resume_cursor_hash(
                resume_trajectory=None,
                resume_token=approval_id if isinstance(approval_id, str) else None,
            )
            now = utc_now()
            self._transition(
                'waiting_approval',
                stage='waiting_approval',
                resume_cursor_hash=cursor_hash,
            )
            self._append_step(
                step_type='observation',
                title='Data Agent is waiting for approval',
                status='completed',
                progress_text='The task is paused until the user approves or rejects runtime package installation.',
                started_at=now,
                completed_at=now,
                detail={
                    'event_type': 'approval_required',
                    'stage': 'waiting_approval',
                },
            )
            self._close()
            return

        if event_type == 'delegate':
            target = _safe_token(event.get('target'), fallback='unknown')
            now = utc_now()
            self._append_step(
                step_type='observation',
                title='Data Agent delegated the task',
                status='completed',
                progress_text='The existing Data Agent completed this turn with a delegation.',
                started_at=now,
                completed_at=now,
                detail={
                    'event_type': 'step_completed',
                    'stage': 'analyzing',
                    'delegation_target': target,
                },
            )
            self.complete()
            return

        if event_type == 'completion':
            self.complete()
            return

        if event_type == 'error':
            self._saw_error = True
            code = event.get('code')
            if not isinstance(code, str) and isinstance(event.get('error'), dict):
                code = event['error'].get('code')
            self._append_step(
                step_type='error',
                title='Data Agent reported an error',
                status='failed',
                progress_text='A Data Agent step failed; raw error and tool output were not copied.',
                completed_at=utc_now(),
                detail={
                    'event_type': 'step_completed',
                    'stage': 'analyzing',
                    'error_code': _safe_token(
                        code,
                        fallback='DATA_AGENT_STEP_FAILED',
                    ),
                },
            )

    def complete(self) -> None:
        if self._closed:
            return
        now = utc_now()
        self._transition('completed', stage='completed')
        self._append_step(
            step_type='progress',
            title='Data Agent task completed',
            status='completed',
            progress_text='The existing Data Agent completed this task.',
            started_at=now,
            completed_at=now,
            detail={'event_type': 'run_completed', 'stage': 'completed'},
        )
        self._close()

    def fail(self, error_code: str = 'DATA_AGENT_STREAM_FAILED') -> None:
        if self._closed:
            return
        now = utc_now()
        self._transition('failed', stage='failed')
        self._append_step(
            step_type='error',
            title='Data Agent task failed',
            status='failed',
            progress_text='The Data Agent task failed. Sensitive details were not copied.',
            started_at=now,
            completed_at=now,
            detail={
                'event_type': 'run_failed',
                'stage': 'failed',
                'error_code': _safe_token(
                    error_code,
                    fallback='DATA_AGENT_STREAM_FAILED',
                ),
            },
        )
        self._close()

    def cancel(self) -> None:
        if self._closed:
            return
        now = utc_now()
        self._transition('cancelled', stage='cancelled')
        self._append_step(
            step_type='progress',
            title='Data Agent task cancelled',
            status='cancelled',
            progress_text='The client stopped consuming the Data Agent stream.',
            started_at=now,
            completed_at=now,
            detail={'event_type': 'run_cancelled', 'stage': 'cancelled'},
        )
        self._close()

    def finish_stream(self) -> None:
        if self._closed:
            return
        if self._saw_error:
            self.fail('DATA_AGENT_STREAM_FAILED')
            return
        now = utc_now()
        self._transition(
            'interrupted',
            stage='interrupted',
            interrupted=True,
        )
        self._append_step(
            step_type='error',
            title='Data Agent task interrupted',
            status='failed',
            progress_text='The stream ended without a terminal event.',
            started_at=now,
            completed_at=now,
            detail={
                'event_type': 'run_interrupted',
                'stage': 'interrupted',
                'error_code': 'STREAM_ENDED_WITHOUT_TERMINAL_EVENT',
            },
        )
        self._close()
