import { describe, expect, it } from 'vitest';

import {
    DEFAULT_BRAND_DESCRIPTION,
    DEFAULT_BRAND_NAME,
    getBrandDescription,
    getBrandName,
    getBrandShortName,
} from '../../src/app/productConfig';

describe('productConfig', () => {
    it('uses Data Formulator defaults when backend branding is absent', () => {
        expect(getBrandName({})).toBe(DEFAULT_BRAND_NAME);
        expect(getBrandShortName({})).toBe(DEFAULT_BRAND_NAME);
        expect(getBrandDescription({})).toBe(DEFAULT_BRAND_DESCRIPTION);
    });

    it('uses non-empty backend branding values', () => {
        const config = {
            APP_BRAND_NAME: 'Business Insight Agent',
            APP_BRAND_SHORT_NAME: 'Insight Agent',
            APP_BRAND_DESCRIPTION: 'Evidence-driven business analysis.',
        };

        expect(getBrandName(config)).toBe('Business Insight Agent');
        expect(getBrandShortName(config)).toBe('Insight Agent');
        expect(getBrandDescription(config)).toBe('Evidence-driven business analysis.');
    });
});
