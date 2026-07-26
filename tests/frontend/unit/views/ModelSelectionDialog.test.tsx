import { configureStore } from '@reduxjs/toolkit';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
    apiRequest: vi.fn(),
}));

vi.mock('react-i18next', () => ({
    initReactI18next: { type: '3rdParty', init: () => undefined },
    useTranslation: () => ({
        t: (key: string, fallback?: unknown) => typeof fallback === 'string' ? fallback : key,
    }),
}));

vi.mock('../../../../src/app/apiClient', () => ({
    apiRequest: (...args: any[]) => apiMocks.apiRequest(...args),
    ApiRequestError: class ApiRequestError extends Error {
        apiError: { message: string };
        constructor(message: string) {
            super(message);
            this.apiError = { message };
        }
    },
}));

import {
    dataFormulatorReducer,
    dfActions,
    type DataFormulatorState,
} from '../../../../src/app/dfSlice';
import { ModelSelectionButton } from '../../../../src/views/ModelSelectionDialog';

function makeStore(config: Partial<DataFormulatorState['serverConfig']>) {
    const store = configureStore({ reducer: dataFormulatorReducer });
    store.dispatch(dfActions.setServerConfig(config as DataFormulatorState['serverConfig']));
    return store;
}

function renderWithStore(store: ReturnType<typeof makeStore>) {
    return render(
        <Provider store={store}>
            <ModelSelectionButton />
        </Provider>,
    );
}

describe('ModelSelectionDialog Business Insight DeepSeek mode', () => {
    beforeEach(() => {
        apiMocks.apiRequest.mockReset();
        apiMocks.apiRequest.mockResolvedValue({ data: { message: '' } });
    });

    it('renders only the restricted DeepSeek user-key entry in Business Insight mode', () => {
        const store = makeStore({
            APP_PRODUCT_MODE: 'business_insight',
            DISABLE_CUSTOM_MODELS: true,
            BIA_USER_DEEPSEEK_KEYS_ENABLED: true,
            BIA_USER_DEEPSEEK_API_BASE: 'https://api.deepseek.com/v1',
            BIA_USER_DEEPSEEK_MODELS: ['deepseek-v4-flash', 'deepseek-v4-pro'],
        });

        renderWithStore(store);
        fireEvent.click(screen.getByText('model.selectModels'));

        expect(screen.getByText(/model.deepSeekRestrictedTip/)).toBeInTheDocument();
        expect(screen.getByDisplayValue('deepseek-v4-flash')).toBeInTheDocument();
        expect(screen.getByDisplayValue('model.deepSeekProviderValue')).toBeDisabled();
        expect(screen.getByDisplayValue('https://api.deepseek.com/v1')).toBeDisabled();
        expect(screen.queryByPlaceholderText('model.providerPlaceholder')).not.toBeInTheDocument();
    });

    it('adds and tests a fixed DeepSeek model with only the API key editable', async () => {
        const store = makeStore({
            APP_PRODUCT_MODE: 'business_insight',
            DISABLE_CUSTOM_MODELS: true,
            BIA_USER_DEEPSEEK_KEYS_ENABLED: true,
            BIA_USER_DEEPSEEK_API_BASE: 'https://api.deepseek.com/v1',
            BIA_USER_DEEPSEEK_MODELS: ['deepseek-v4-flash', 'deepseek-v4-pro'],
        });

        renderWithStore(store);
        fireEvent.click(screen.getByText('model.selectModels'));
        fireEvent.change(screen.getByPlaceholderText('model.deepSeekApiKeyPlaceholder'), {
            target: { value: 'sk-browser-only' },
        });
        const addButton = screen.getAllByLabelText('model.addAndTestModel').find((el) => el.tagName === 'BUTTON');
        expect(addButton).toBeTruthy();
        fireEvent.click(addButton!);

        await waitFor(() => expect(apiMocks.apiRequest).toHaveBeenCalled());
        const body = JSON.parse(apiMocks.apiRequest.mock.calls[0][1].body);
        expect(body.model).toMatchObject({
            endpoint: 'openai',
            model: 'deepseek-v4-flash',
            api_key: 'sk-browser-only',
            api_base: 'https://api.deepseek.com/v1',
            api_version: '',
        });
        expect(store.getState().models[0]).toMatchObject(body.model);
    });
});
