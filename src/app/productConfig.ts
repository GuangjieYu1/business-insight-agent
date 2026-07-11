// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

export const DEFAULT_PRODUCT_MODE = 'data_formulator';
export const DEFAULT_BRAND_NAME = 'Data Formulator';
export const DEFAULT_BRAND_SHORT_NAME = 'Data Formulator';
export const DEFAULT_BRAND_DESCRIPTION = 'AI-powered data exploration and visualization.';

export type ProductMode = typeof DEFAULT_PRODUCT_MODE | 'business_insight';

export interface ProductBrandConfig {
    APP_PRODUCT_MODE?: ProductMode;
    APP_BRAND_NAME?: string;
    APP_BRAND_SHORT_NAME?: string;
    APP_BRAND_DESCRIPTION?: string;
}

const clean = (value: string | undefined): string | undefined => {
    const trimmed = value?.trim();
    return trimmed ? trimmed : undefined;
};

export const getBrandName = (config?: ProductBrandConfig | null): string =>
    clean(config?.APP_BRAND_NAME) ?? DEFAULT_BRAND_NAME;

export const getBrandShortName = (config?: ProductBrandConfig | null): string =>
    clean(config?.APP_BRAND_SHORT_NAME) ?? getBrandName(config);

export const getBrandDescription = (config?: ProductBrandConfig | null): string =>
    clean(config?.APP_BRAND_DESCRIPTION) ?? DEFAULT_BRAND_DESCRIPTION;
