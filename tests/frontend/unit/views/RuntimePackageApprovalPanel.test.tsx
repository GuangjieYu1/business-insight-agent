import React from 'react';
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { RuntimePackageApprovalPanel } from '../../../../src/views/AgentPausePanel';

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string, params?: Record<string, string>) => {
      const labels: Record<string, string> = {
        'chartRec.runtimePackageApprovalTitle': 'Runtime package approval',
        'chartRec.runtimePackageApprovalIntro': 'Approve the requested package.',
        'chartRec.runtimePackageApprovalSource': 'Source: ' + params?.source + '; target: ' + params?.target,
        'chartRec.runtimePackageApprovalRisk': 'Package code will run in the server sandbox.',
        'chartRec.runtimePackageApprove': 'Approve',
        'chartRec.runtimePackageReject': 'Reject',
        'chartRec.runtimePackageCancel': 'Cancel',
        'chartRec.runtimePackageInstalling': 'Installing ' + params?.packages,
        'chartRec.runtimePackageInstalled': 'Installed ' + params?.packages,
        'chartRec.runtimePackageRejected': 'Rejected ' + params?.packages,
        'chartRec.runtimePackageInstallFailed': 'Install failed ' + params?.packages,
        'chartRec.minimizeClarification': 'Minimize',
        'chartRec.expandClarification': 'Expand',
      };
      return labels[key] || key;
    },
  }),
}));

const approval = {
  id: 'approval_001',
  packages: ['xgboost'],
};

describe('RuntimePackageApprovalPanel', () => {
  it('lets the user approve or reject a pending package request', () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();

    render(
      <RuntimePackageApprovalPanel
        approval={approval}
        onApprove={onApprove}
        onReject={onReject}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));

    expect(onApprove).toHaveBeenCalledOnce();
    expect(onReject).toHaveBeenCalledOnce();
    expect(screen.getByText('xgboost')).toBeInTheDocument();
  });

  it('locks the decision while installation is in progress', () => {
    render(
      <RuntimePackageApprovalPanel
        approval={approval}
        status="installing"
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('Installing xgboost')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled();
  });
});
