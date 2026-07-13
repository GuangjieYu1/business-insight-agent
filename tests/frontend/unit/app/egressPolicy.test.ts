import { describe, expect, it } from 'vitest';

import {
    assertOnlineChartifactAllowed,
    ONLINE_CHARTIFACT_BLOCKED,
} from '../../../../src/app/egressPolicy';

describe('online Chartifact egress policy', () => {
    it('blocks Business Insight mode before online content can be sent', () => {
        expect(() => assertOnlineChartifactAllowed({
            APP_PRODUCT_MODE: 'business_insight',
            BIA_ONLINE_CHARTIFACT_BLOCKED: true,
        })).toThrow(ONLINE_CHARTIFACT_BLOCKED);
    });

    it('keeps the original Data Formulator mode available', () => {
        expect(() => assertOnlineChartifactAllowed({
            APP_PRODUCT_MODE: 'data_formulator',
            BIA_ONLINE_CHARTIFACT_BLOCKED: false,
        })).not.toThrow();
    });
});
