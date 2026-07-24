import React from 'react';
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApprovalPanel, ClarificationPanel } from '../../../../src/views/AgentPausePanel';

vi.mock('react-i18next', () => ({
  // The panel now lives in `AgentPausePanel.tsx` which transitively pulls
  // in `dfSlice` → `i18n/index` → `.use(initReactI18next)`. Provide a no-op
  // plugin shim so the i18n init code path succeeds under the mock.
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string, params?: Record<string, any>) => {
      const labels: Record<string, string> = {
        'chartRec.clarificationTitle': 'Agent needs clarification',
        'chartRec.clarificationQuestionLabel': `${params?.index}.`,
        'chartRec.optionalClarification': '(optional)',
        'chartRec.freeTextClarificationPlaceholder': 'Type your answer...',
        'chartRec.freeTextClarificationHint': 'Type your answer in the chat box below.',
        'chartRec.approvalTitle': 'Approve package install',
        'chartRec.approvalReject': 'Reject',
        'chartRec.approvalMinimize': 'Minimize approval',
        'chartRec.approvalExpand': 'Expand approval',
        'chartRec.approvalDomesticBody': `Install ${params?.packages} from domestic mirrors?`,
        'chartRec.approvalSourceOrder': `Sources: ${params?.sources}`,
        'chartRec.approvalUnknownPackage': 'unknown package',
        'chartRec.approvalApproveDomestic': 'Approve domestic install',
      };
      return labels[key] || key;
    },
  }),
}));

describe('ClarificationPanel', () => {
  it('submits a single-choice question immediately when an option is clicked', () => {
    const onSubmit = vi.fn();

    render(
      <ClarificationPanel
        questions={[{
          text: 'Which metric?',
          responseType: 'single_choice',
          options: [{ label: 'Revenue' }],
        }]}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Revenue' }));

    expect(onSubmit).toHaveBeenCalledWith([{
      question_index: 0,
      answer: 'Revenue',
      source: 'option',
    }]);
  });

  it('records partial selections via onSelectAnswer without submitting', () => {
    const onSubmit = vi.fn();
    const onSelectAnswer = vi.fn();

    render(
      <ClarificationPanel
        questions={[
          {
            text: 'Which metric?',
            responseType: 'single_choice',
            options: [{ label: 'Revenue' }],
          },
          {
            text: 'Which period?',
            responseType: 'single_choice',
            options: [{ label: 'Last 12 months' }],
          },
        ]}
        onSelectAnswer={onSelectAnswer}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Revenue' }));

    expect(onSelectAnswer).toHaveBeenCalledWith(0, {
      question_index: 0,
      answer: 'Revenue',
      source: 'option',
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('shows a chat-box hint for free-text questions and renders no input', () => {
    const onSubmit = vi.fn();

    render(
      <ClarificationPanel
        questions={[{
          text: 'Anything else to share?',
          responseType: 'free_text',
        }]}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('Type your answer in the chat box below.')).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('Type your answer...')).toBeNull();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('renders package approval details and wires approve/reject actions', () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();

    render(
      <ApprovalPanel
        approval={{
          id: 'approval_123',
          kind: 'python_package_install',
          packages: ['xgboost', 'shap'],
          modules: ['xgboost', 'shap'],
          sources: [
            { id: 'primary', label: 'Aliyun HTTPS', url: 'https://mirrors.aliyun.com/pypi/simple/' },
            { id: 'secondary', label: 'Tsinghua TUNA', url: 'https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple' },
          ],
        }}
        onApprove={onApprove}
        onReject={onReject}
      />,
    );

    expect(screen.getByText('Install xgboost, shap from domestic mirrors?')).toBeInTheDocument();
    expect(screen.getByText('Sources: Aliyun HTTPS → Tsinghua TUNA')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Approve domestic install' }));
    expect(onApprove).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getAllByRole('button', { name: 'Reject' })[0]);
    expect(onReject).toHaveBeenCalledTimes(1);
  });
});
