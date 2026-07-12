// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { configureStore } from '@reduxjs/toolkit'
import { dataFormulatorReducer, type DataFormulatorState } from './dfSlice';
import { insightReducer, type InsightState } from '../insight/store/profilingSlice';

import { persistReducer, persistStore } from 'redux-persist'
import localforage from 'localforage';

export type RootState = DataFormulatorState & {
    insight: InsightState;
};

const persistConfig = {
    key: 'root',
    //storage,
    storage: localforage,
    // globalModels are always fetched fresh from the server on each app start,
    // so there is no need (and it would cause stale-data issues) to persist them.
    // In-progress flags are transient and should not survive page refreshes.
    blacklist: ['serverConfig', 'globalModels', 'chartSynthesisInProgress', 'chartInsightInProgress', 'insight'],
}

const rootReducer = (state: RootState | undefined, action: { type: string }) => {
    const dataFormulatorState = state
        ? (({ insight: _ignored, ...rest }: RootState) => rest)(state)
        : undefined;
    const nextDataFormulatorState = dataFormulatorReducer(dataFormulatorState, action);
    const nextInsightState = insightReducer(state?.insight, action);

    return {
        ...nextDataFormulatorState,
        insight: nextInsightState,
    };
};

const persistedReducer = persistReducer<ReturnType<typeof rootReducer>>(persistConfig, rootReducer)

let store = configureStore({
    reducer: persistedReducer,
    middleware: (getDefaultMiddleware) =>
        getDefaultMiddleware({
            serializableCheck: false,
    }),
})

export type AppDispatch = typeof store.dispatch

export const persistor = persistStore(store);

export default store;

// Export store instance for use in utilities
export { store };
