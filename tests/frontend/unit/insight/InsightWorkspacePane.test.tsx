import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ProfileColumnsTable } from '../../../../src/insight/components/ProfileColumnsTable';
import { ProfileIssueList } from '../../../../src/insight/components/ProfileIssueList';
import { ProfileOverviewCards } from '../../../../src/insight/components/ProfileOverviewCards';
import type { DatasetProfile } from '../../../../src/insight/types';

const t = (key: string, params?: Record<string, unknown>) => {
    if (key === 'insight.profile.metrics.duplicateRowsHelper') {
        return `${params?.count} rows are part of duplicate groups`;
    }
    if (key === 'insight.profile.columns.nulls') {
        return `${params?.count} nulls (${params?.ratio})`;
    }
    if (key === 'insight.profile.columns.distincts') {
        return `${params?.count} distinct (${params?.ratio})`;
    }
    if (key === 'insight.profile.columns.numericConflicts') {
        return `Numeric conflicts: ${params?.count}`;
    }
    if (key === 'insight.profile.columns.datetimeConflicts') {
        return `Datetime conflicts: ${params?.count}`;
    }
    if (key.startsWith('insight.severity.')) {
        return `${key}:${params?.count ?? ''}`;
    }
    return key;
};

function createProfile(): DatasetProfile {
    return {
        id: 'profile_sales',
        schema_version: '1.0',
        workspace_id: 'ws-1',
        created_at: '2026-07-12T00:00:00Z',
        updated_at: '2026-07-12T00:00:00Z',
        dataset_id: 'dataset_sales',
        version_id: 'version_000',
        source_content_hash: 'hash-1',
        profiler_version: 'dataset-profiler-v1',
        configuration_hash: 'cfg-1',
        file_ref: 'datasets/dataset_sales/versions/version_000.parquet',
        profile_ref: 'datasets/dataset_sales/profiles/version_000.json',
        row_count: 10,
        column_count: 3,
        duplicate_row_count: 1,
        duplicate_row_ratio: 0.1,
        duplicate_group_member_count: 2,
        duplicate_group_member_ratio: 0.2,
        duplicate_excess_row_count: 1,
        duplicate_excess_row_ratio: 0.1,
        sample_policy: 'disabled',
        redaction_applied: true,
        sensitive_data_detected: true,
        columns: [
            {
                name: 'sales',
                pandas_dtype: 'object',
                inferred_type: 'text',
                row_count: 10,
                non_null_count: 8,
                null_count: 2,
                null_ratio: 0.2,
                distinct_count: 6,
                distinct_ratio: 0.6,
                value_storage_policy: 'redacted_sensitive',
                sensitive_data_detected: true,
                redaction_applied: true,
                top_values: [],
                sample_values: [],
                python_types: ['str'],
                numeric_parseable_count: 7,
                numeric_parse_conflict_count: 1,
                datetime_parseable_count: 0,
                datetime_parse_conflict_count: 0,
                quality_issue_types: ['numeric_parse_conflict'],
            },
        ],
        quality_issues: [
            {
                issue_type: 'numeric_parse_conflict',
                severity: 'medium',
                scope: { column: 'sales' },
                metrics: { conflict_count: 1 },
                message: 'Some values cannot be parsed as numbers.',
            },
        ],
    };
}

describe('profiling display components', () => {
    it('renders overview, issue evidence, and column flags', () => {
        const profile = createProfile();

        render(
            <div>
                <ProfileOverviewCards profile={profile} t={t as any} />
                <ProfileIssueList profile={profile} t={t as any} />
                <ProfileColumnsTable profile={profile} t={t as any} />
            </div>,
        );

        expect(screen.getByText('insight.profile.metrics.rows')).toBeInTheDocument();
        expect(screen.getByText('Some values cannot be parsed as numbers.')).toBeInTheDocument();
        expect(screen.getByText('insight.profile.columns.sensitive')).toBeInTheDocument();
        expect(screen.getAllByText('insight.issueTypes.numeric_parse_conflict')).toHaveLength(2);
        expect(screen.getByText('Numeric conflicts: 1')).toBeInTheDocument();
    });
});
