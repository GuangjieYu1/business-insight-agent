import '@testing-library/jest-dom/vitest';

if (typeof globalThis.localStorage === 'undefined' || typeof globalThis.localStorage.getItem !== 'function') {
    const storage = new Map<string, string>();
    const mockStorage = {
        getItem: (key: string) => (storage.has(key) ? storage.get(key)! : null),
        setItem: (key: string, value: string) => {
            storage.set(key, String(value));
        },
        removeItem: (key: string) => {
            storage.delete(key);
        },
        clear: () => {
            storage.clear();
        },
        key: (index: number) => Array.from(storage.keys())[index] ?? null,
        get length() {
            return storage.size;
        },
    } satisfies Storage;

    Object.defineProperty(globalThis, 'localStorage', {
        value: mockStorage,
        configurable: true,
    });
}
