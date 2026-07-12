const percentFormatter = new Intl.NumberFormat(undefined, {
    style: 'percent',
    maximumFractionDigits: 1,
});

const numberFormatter = new Intl.NumberFormat(undefined, {
    maximumFractionDigits: 0,
});

const decimalFormatter = new Intl.NumberFormat(undefined, {
    maximumFractionDigits: 2,
});

export const formatPercent = (value: number): string => percentFormatter.format(value);

export const formatInteger = (value: number): string => numberFormatter.format(value);

export const formatMetricValue = (value: unknown): string => {
    if (typeof value === 'number') {
        return Number.isInteger(value) ? formatInteger(value) : decimalFormatter.format(value);
    }

    if (typeof value === 'boolean') {
        return value ? 'true' : 'false';
    }

    if (typeof value === 'string') {
        return value.length > 80 ? `${value.slice(0, 77)}...` : value;
    }

    if (Array.isArray(value)) {
        return value.join(', ');
    }

    if (value && typeof value === 'object') {
        return JSON.stringify(value);
    }

    return String(value ?? '');
};

export const formatMetricLabel = (value: string): string =>
    value
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (char) => char.toUpperCase());
