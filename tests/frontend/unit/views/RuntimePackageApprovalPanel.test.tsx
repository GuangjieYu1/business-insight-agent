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
        'chartRec.runtimePackageOfficialApprovalTitle': 'Official PyPI approval',
        'chartRec.runtimePackageApprovalIntro': 'Approve the requested package.',
        'chartRec.runtimePackageOfficialApprovalIntro': 'Approve official PyPI.',
        'chartRec.runtimePackageApprovalSource': 'Source: ' + params?.source + '; target: ' + params?.target,
        'chartRec.runtimePackageCurrentSource': 'Current source: ' + params?.source,
        'chartRec.runtimePackageApprovalRisk': 'Package code will run in the server sandbox.',
        'chartRec.runtimePackageApprove': 'Approve',
        'chartRec.runtimePackageApproveOfficial': 'Use official PyPI',
        'chartRec.runtimePackageReject': 'Reject',
        'chartRec.runtimePackageCancel': 'Cancel',
        'chartRec.runtimePackageInstalling': 'Installing ' + params?.packages + ' from ' + params?.source,
        'chartRec.runtimePackageRetryingSecondary': 'Retrying ' + params?.packages + ' from ' + params?.source,
        'chartRec.runtimePackageAwaitingOfficial': 'Waiting official ' + params?.packages,
        'chartRec.runtimePackageInstalled': 'Installed ' + params?.packages + ' ' + (params?.versions || ''),
        'chartRec.runtimePackageRejected': 'Rejected ' + params?.packages,
        'chartRec.runtimePackageInstallFailed': 'Install failed ' + params?.packages + ' ' + params?.errorCode,
        'chartRec.runtimePackageFailureDetail': 'Reason: ' + params?.error,
        'chartRec.runtimePackageFallbackHint': 'Fallback active',
        'chartRec.runtimePackageDefaultSource': 'default source',
        'chartRec.runtimePackageSecondarySource': 'secondary source',
        'chartRec.runtimePackageUnknownPackage': 'runtime package',
        'chartRec.runtimePackageUnknownError': 'unknown_install_error',
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

    expect(screen.getByText('Installing xgboost from default source')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled();
  });

  it('shows retry source progress and disables duplicate decisions', () => {
    render(
      <RuntimePackageApprovalPanel
        approval={{ ...approval, sources: [{ id: 'primary', label: 'Aliyun', domain: 'mirrors.aliyun.com' }, { id: 'secondary', label: 'Tsinghua', domain: 'mirrors.tuna.tsinghua.edu.cn' }] }}
        status="retrying_secondary"
        source={{ id: 'secondary', label: 'Tsinghua', domain: 'mirrors.tuna.tsinghua.edu.cn' }}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('Retrying xgboost from Tsinghua (mirrors.tuna.tsinghua.edu.cn)')).toBeInTheDocument();
    expect(screen.getByText('Current source: Tsinghua (mirrors.tuna.tsinghua.edu.cn)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled();
  });

  it('shows sanitized failure detail and fallback hint at terminal failure', () => {
    render(
      <RuntimePackageApprovalPanel
        approval={approval}
        status="failed"
        error="No module named pip"
        errorCode="installer_unavailable"
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('Install failed xgboost installer_unavailable')).toBeInTheDocument();
    expect(screen.getByText('Reason: No module named pip')).toBeInTheDocument();
    expect(screen.getByText('Fallback active')).toBeInTheDocument();
  });

  it('uses a distinct official PyPI approval action', () => {
    render(
      <RuntimePackageApprovalPanel
        approval={{ ...approval, kind: 'official_pypi_fallback' }}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('Official PyPI approval')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Use official PyPI' })).toBeEnabled();
  });
});
