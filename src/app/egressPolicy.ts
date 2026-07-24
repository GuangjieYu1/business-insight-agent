import type { ServerConfig } from './dfSlice';

export const ONLINE_CHARTIFACT_BLOCKED = 'BIA_ONLINE_CHARTIFACT_BLOCKED';

export function assertOnlineChartifactAllowed(
    config: Pick<
        ServerConfig,
        'APP_PRODUCT_MODE' | 'BIA_ONLINE_CHARTIFACT_BLOCKED'
    >,
): void {
    if (
        config.APP_PRODUCT_MODE === 'business_insight'
        || config.BIA_ONLINE_CHARTIFACT_BLOCKED
    ) {
        throw new Error(ONLINE_CHARTIFACT_BLOCKED);
    }
}
