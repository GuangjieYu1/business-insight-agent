import { describe, expect, it } from 'vitest';

import { getSerializableState } from '../../../../src/app/useAutoSave';
import type { DataFormulatorState } from '../../../../src/app/dfSlice';

describe('getSerializableState model secrets', () => {
    it('does not include browser-stored user model API keys in workspace autosave payload', () => {
        const state = {
            activeWorkspace: { id: 'ws-1', displayName: 'Workspace 1' },
            models: [
                {
                    id: 'deepseek-user',
                    endpoint: 'openai',
                    model: 'deepseek-v4-flash',
                    api_key: 'sk-browser-only',
                    api_base: 'https://api.deepseek.com/v1',
                    api_version: '',
                },
            ],
            selectedModelId: 'deepseek-user',
            testedModels: [{ id: 'deepseek-user', status: 'ok', message: '' }],
            tables: [],
        } as unknown as DataFormulatorState;

        const serializable = getSerializableState(state);

        expect(serializable.models).toBeUndefined();
        expect(serializable.selectedModelId).toBeUndefined();
        expect(serializable.testedModels).toBeUndefined();
        expect(JSON.stringify(serializable)).not.toContain('sk-browser-only');
    });
});
