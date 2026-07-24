import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ConnectorTablePreview } from '../../../../src/components/ConnectorTablePreview';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, params?: Record<string, any>) => {
            const map: Record<string, string> = {
                'connectorPreview.colName': 'Column',
                'connectorPreview.colType': 'Type',
                'connectorPreview.colDesc': 'Description',
            };
            return map[key] ?? params?.defaultValue ?? key;
        },
    }),
}));

vi.mock('../../../../src/app/apiClient', () => ({
    apiRequest: vi.fn(),
}));

vi.mock('../../../../src/app/utils', () => ({
    fetchWithIdentity: vi.fn(),
    CONNECTOR_ACTION_URLS: {
        COLUMN_VALUES: '/api/connectors/column-values',
        PREVIEW_DATA: '/api/connectors/preview-data',
    },
}));

describe('ConnectorTablePreview metadata display', () => {
    const baseProps = {
        connectorId: 'warehouse',
        sourceTable: { id: 'orders', name: 'orders' },
        displayName: 'orders',
        columns: [
            { name: 'order_id', type: 'NUMERIC', description: 'Primary order key', verbose_name: 'Order ID' },
            { name: 'region', type: 'STRING' },
            { name: 'total', type: 'NUMERIC', description: 'Sum of line items', expression: 'SUM(line_items.amount)' },
        ],
        sampleRows: [{ order_id: 1, region: 'east', total: 12.5 }],
        rowCount: 1,
        loading: false,
        alreadyLoaded: false,
        onLoad: vi.fn(),
    };

    it('shows the table-level metadata description inline', () => {
        render(
            <ConnectorTablePreview
                {...baseProps}
                tableDescription="Orders from the warehouse"
            />,
        );

        expect(screen.getByText('Orders from the warehouse')).toBeInTheDocument();
        expect(screen.queryByText('Source metadata')).not.toBeInTheDocument();
    });

    it('exposes column metadata on preview headers', () => {
        render(<ConnectorTablePreview {...baseProps} />);

        const orderHeader = screen.getByText('order_id');
        expect(orderHeader.getAttribute('aria-label')).toContain('Primary order key');
        expect(orderHeader.getAttribute('aria-label')).toContain('(Order ID)');

        const totalHeader = screen.getByText('total');
        expect(totalHeader.getAttribute('aria-label')).toContain('Sum of line items');
        expect(totalHeader.getAttribute('aria-label')).toContain('SUM(line_items.amount)');
    });
});