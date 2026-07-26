// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import React, { useEffect, useState } from 'react';
import '../scss/App.scss';

import { useDispatch, useSelector } from "react-redux";
import {
    DataFormulatorState,
    dfActions,
    ModelConfig,
    dfSelectors,
} from '../app/dfSlice'
import Chip from '@mui/material/Chip';

import _ from 'lodash';

import {
    Button,
    Tooltip,
    Typography,
    IconButton,
    DialogTitle,
    Dialog,
    DialogContent,
    DialogActions,
    Radio,
    TextField,
    TableContainer,
    TableHead,
    Table,
    TableCell,
    TableRow,
    TableBody,
    Autocomplete,
    CircularProgress,
    FormControl,
    Select,
    SelectChangeEvent,
    MenuItem,
    OutlinedInput,
    Paper,
    Box,
    Divider,
    Checkbox,
    Switch,
    FormControlLabel,
} from '@mui/material';


import { alpha, styled, useTheme } from '@mui/material/styles';

import AddCircleIcon from '@mui/icons-material/AddCircle';
import ClearIcon from '@mui/icons-material/Clear';
import VisibilityIcon from '@mui/icons-material/Visibility';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';

import { getUrls } from '../app/utils';
import { apiRequest, ApiRequestError } from '../app/apiClient';
import { useTranslation } from 'react-i18next';


const decodeHtmlEntities = (text: string): string => {
    const textarea = document.createElement('textarea');
    textarea.innerHTML = text;
    return textarea.value;
};

// Add this helper function at the top of the file, after the imports
const simpleHash = (str: string): string => {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // Convert to 32-bit integer
    }
    return Math.abs(hash).toString(36);
};

export const ModelSelectionButton: React.FC<{}> = ({ }) => {
    const theme = useTheme();
    const { t } = useTranslation();

    const dispatch = useDispatch();
    const globalModels = useSelector((state: DataFormulatorState) => state.globalModels ?? []);
    const models = useSelector((state: DataFormulatorState) => state.models);
    const selectedModelId = useSelector((state: DataFormulatorState) => state.selectedModelId);
    const testedModels = useSelector((state: DataFormulatorState) => state.testedModels);

    const [modelDialogOpen, setModelDialogOpen] = useState<boolean>(false);
    const [showKeys, setShowKeys] = useState<boolean>(false);
    const [providerModelOptions, setProviderModelOptions] = useState<{[key: string]: string[]}>({
        'openai': [],
        'azure': [],
        'anthropic': [],
        'gemini': [],
        'ollama': []
    });
    const serverConfig = useSelector((state: DataFormulatorState) => state.serverConfig);

    let updateModelStatus = (model: ModelConfig, status: 'ok' | 'error' | 'testing' | 'unknown', message: string) => {
        dispatch(dfActions.updateModelStatus({id: model.id, status, message}));
    }
    let getStatus = (id: string | undefined) => {
        return id != undefined ? (testedModels.find(t => (t.id == id))?.status || 'unknown') : 'unknown';
    }

    // Helper functions for slot management
    const [tempSelectedModelId, setTempSelectedModelId] = useState<string | undefined>(selectedModelId);
    const [newEndpoint, setNewEndpoint] = useState<string>(""); // openai, azure, ollama etc
    const [newModel, setNewModel] = useState<string>("");
    const [newApiKey, setNewApiKey] = useState<string>("");
    const [newApiBase, setNewApiBase] = useState<string>("");
    const [newApiVersion, setNewApiVersion] = useState<string>("");

    // Build provider→model dropdown options from globalModels (already in Redux).
    // This runs whenever globalModels updates (phase 1 instant list → phase 2 with statuses).
    useEffect(() => {
        const modelsByProvider: {[key: string]: string[]} = {
            'openai': [],
            'azure': [],
            'anthropic': [],
            'gemini': [],
            'ollama': []
        };

        globalModels.forEach((modelConfig: any) => {
            const provider = modelConfig.endpoint;
            const model = modelConfig.model;

            if (provider && model && !modelsByProvider[provider]) {
                modelsByProvider[provider] = [];
            }
            if (provider && model && !modelsByProvider[provider].includes(model)) {
                modelsByProvider[provider].push(model);
            }
        });

        setProviderModelOptions(modelsByProvider);
    }, [globalModels]);


    const isBusinessInsight = serverConfig.APP_PRODUCT_MODE === 'business_insight';
    const deepSeekModels = serverConfig.BIA_USER_DEEPSEEK_MODELS?.length
        ? serverConfig.BIA_USER_DEEPSEEK_MODELS
        : ['deepseek-v4-flash', 'deepseek-v4-pro'];
    const deepSeekApiBase = serverConfig.BIA_USER_DEEPSEEK_API_BASE || 'https://api.deepseek.com/v1';
    const shouldShowDeepSeekEntry = isBusinessInsight && serverConfig.BIA_USER_DEEPSEEK_KEYS_ENABLED;
    const shouldShowGenericCustomEntry = !serverConfig.DISABLE_CUSTOM_MODELS && !shouldShowDeepSeekEntry;

    useEffect(() => {
        if (!shouldShowDeepSeekEntry) return;
        const firstDeepSeekModel = deepSeekModels[0] || '';
        if (!deepSeekModels.includes(newModel)) {
            setNewModel(firstDeepSeekModel);
        }
        if (newEndpoint !== 'openai') {
            setNewEndpoint('openai');
        }
        if (newApiBase !== deepSeekApiBase) {
            setNewApiBase(deepSeekApiBase);
        }
        if (newApiVersion !== '') {
            setNewApiVersion('');
        }
    }, [shouldShowDeepSeekEntry, deepSeekApiBase, deepSeekModels.join('|')]);

    const pendingEndpoint = shouldShowDeepSeekEntry ? 'openai' : newEndpoint;
    const pendingModel = shouldShowDeepSeekEntry && !deepSeekModels.includes(newModel)
        ? (deepSeekModels[0] || '')
        : newModel;
    const pendingApiBase = shouldShowDeepSeekEntry ? deepSeekApiBase : newApiBase;
    const pendingApiVersion = shouldShowDeepSeekEntry ? '' : newApiVersion;

    let modelExists = models.some(m =>
        m.endpoint == pendingEndpoint && m.model == pendingModel && m.api_base == pendingApiBase
        && m.api_key == newApiKey.trim() && (m.api_version || '') == pendingApiVersion);

    let testModel = (model: ModelConfig) => {
        updateModelStatus(model, 'testing', "");
        apiRequest(getUrls().TEST_MODEL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model }),
        })
            .then(({ data }) => {
                updateModelStatus(model, 'ok', data.message || "");
                if (!tempSelectedModelId) {
                    setTempSelectedModelId(model.id);
                }
            }).catch((error) => {
                const msg = error instanceof ApiRequestError
                    ? error.apiError.message
                    : error.message;
                updateModelStatus(model, 'error', msg);
            });
    }

    let readyToTest = shouldShowDeepSeekEntry
        ? Boolean(pendingModel && newApiKey.trim())
        : Boolean(newModel && (newApiKey || newApiBase));

    const inputSx = {
        '& .MuiOutlinedInput-root': {
            fontSize: '0.75rem',
            borderRadius: 0.5,
            backgroundColor: 'rgba(0,0,0,0.02)',
            height: 28,
            '& fieldset': { borderColor: 'divider' },
            '&:hover fieldset': { borderColor: 'text.disabled' },
            '&.Mui-focused fieldset': { borderColor: 'primary.main' },
        },
        '& .MuiOutlinedInput-input': { px: 1, py: 0 },
    };

    const buildPendingModel = (): ModelConfig => {
        const endpoint = pendingEndpoint;
        const modelName = pendingModel;
        const apiKey = newApiKey.trim();
        const apiBase = pendingApiBase;
        const apiVersion = pendingApiVersion;
        const idString = `${endpoint}-${modelName}-${apiKey}-${apiBase}-${apiVersion}`;
        return {
            endpoint,
            model: modelName,
            api_key: apiKey,
            api_base: apiBase,
            api_version: apiVersion,
            id: simpleHash(idString),
        };
    };

    const resetNewModelFields = () => {
        setNewEndpoint(shouldShowDeepSeekEntry ? 'openai' : '');
        setNewModel(shouldShowDeepSeekEntry ? (deepSeekModels[0] || '') : '');
        setNewApiKey('');
        setNewApiBase(shouldShowDeepSeekEntry ? deepSeekApiBase : '');
        setNewApiVersion('');
    };

    const testAndAssignModel = (model: ModelConfig) => {
        updateModelStatus(model, 'testing', '');
        apiRequest(getUrls().TEST_MODEL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model }),
        })
            .then(({ data }) => {
                updateModelStatus(model, 'ok', data.message || '');
                setTempSelectedModelId(model.id);
            }).catch((error) => {
                const msg = error instanceof ApiRequestError
                    ? error.apiError.message
                    : error.message;
                updateModelStatus(model, 'error', msg);
            });
    };

    const addPendingModel = (event: React.MouseEvent<HTMLButtonElement>) => {
        event.stopPropagation();
        const model = buildPendingModel();
        dispatch(dfActions.addModel(model));
        testAndAssignModel(model);
        resetNewModelFields();
    };

    const renderAddButton = () => (
        <Tooltip title={modelExists ? t('model.providerModelExists') : t('model.addAndTestModel')}>
            <span>
                <IconButton
                    aria-label={t('model.addAndTestModel')}
                    color={modelExists ? 'error' : 'primary'}
                    disabled={!readyToTest || modelExists}
                    size="small"
                    sx={{ cursor: modelExists ? 'help' : 'pointer', p: 0.25 }}
                    onClick={addPendingModel}
                >
                    <AddCircleIcon sx={{ fontSize: 18 }} />
                </IconButton>
            </span>
        </Tooltip>
    );

    const deepSeekModelEntry = <TableRow
        key="new-deepseek-model-entry"
        sx={{ '&:last-child td, &:last-child th': { border: 0 }, '& td': { py: 1 } }}
    >
        <TableCell align="left">
            <TextField
                select
                size="small"
                fullWidth
                variant="outlined"
                value={pendingModel}
                onChange={(event) => setNewModel(event.target.value)}
                sx={inputSx}
                slotProps={{ input: { 'aria-label': t('model.deepSeekModelAria') } }}
            >
                {deepSeekModels.map(modelName => (
                    <MenuItem key={modelName} value={modelName} sx={{ fontSize: '0.75rem' }}>
                        {modelName}
                    </MenuItem>
                ))}
            </TextField>
        </TableCell>
        <TableCell align="left">
            <TextField
                fullWidth
                size="small"
                type={showKeys ? 'text' : 'password'}
                variant="outlined"
                sx={inputSx}
                placeholder={t('model.deepSeekApiKeyPlaceholder')}
                value={newApiKey}
                onChange={(event) => setNewApiKey(event.target.value)}
                autoComplete="off"
                inputProps={{ autoComplete: 'off', 'data-form-type': 'other' }}
            />
        </TableCell>
        <TableCell align="left">
            <TextField
                size="small"
                fullWidth
                disabled
                variant="outlined"
                sx={inputSx}
                value={t('model.deepSeekProviderValue')}
            />
        </TableCell>
        <TableCell align="left">
            <TextField
                size="small"
                fullWidth
                disabled
                variant="outlined"
                sx={inputSx}
                value={deepSeekApiBase}
            />
        </TableCell>
        <TableCell align="left">
            <TextField
                size="small"
                fullWidth
                disabled
                variant="outlined"
                sx={inputSx}
                value=""
                placeholder={t('model.notApplicable')}
            />
        </TableCell>
        <TableCell align="left">
            {renderAddButton()}
        </TableCell>
        <TableCell align="right">
            <Tooltip title={t('model.clear')}>
                <IconButton size="small" sx={{ p: 0.25 }} onClick={(event) => { event.stopPropagation(); resetNewModelFields(); }}>
                    <ClearIcon sx={{ fontSize: 14 }} />
                </IconButton>
            </Tooltip>
        </TableCell>
    </TableRow>;

    const genericModelEntry = <TableRow
        key={`new-model-entry`}
        sx={{ '&:last-child td, &:last-child th': { border: 0 }, '& td': { py: 1 } }}
    >
        <TableCell align="left">
            <TextField
                size="small"
                fullWidth
                variant="outlined"
                value={newModel}
                onChange={(event) => { setNewModel(event.target.value); }}
                placeholder={t('model.modelPlaceholder')}
                error={newEndpoint != "" && !newModel}
                sx={inputSx}
                slotProps={{ input: { 'aria-label': t('model.enterModelName') } }}
                autoComplete='off'
                inputProps={{ 'data-form-type': 'other' }}
            />
        </TableCell>
        <TableCell align="left">
            <TextField fullWidth size="small" type={showKeys ? "text" : "password"}
                variant="outlined"
                sx={inputSx}
                placeholder={t('model.optionalKeylessEndpoint')}
                value={newApiKey}
                onChange={(event: any) => { setNewApiKey(event.target.value); }}
                autoComplete='off'
                inputProps={{ autoComplete: 'off', 'data-form-type': 'other' }}
            />
        </TableCell>
        <TableCell align="left">
            <Autocomplete
                freeSolo
                value={newEndpoint}
                onChange={(event: any, newValue: string | null) => {
                    setNewEndpoint(newValue || "");
                    if (newModel == "" && newValue == "openai" && providerModelOptions.openai.length > 0) {
                        setNewModel(providerModelOptions.openai[0]);
                    }
                    if (!newApiVersion && newValue == "azure") {
                        setNewApiVersion("2024-02-15");
                    }
                }}
                options={['openai', 'azure', 'ollama', 'anthropic', 'gemini']}
                renderOption={(props, option) => (
                    <Typography {...props} onClick={() => setNewEndpoint(option)} sx={{ fontSize: "0.75rem" }}>
                        {option}
                    </Typography>
                )}
                renderInput={(params) => (
                    <TextField
                        {...params}
                        placeholder={t('model.providerPlaceholder')}
                        size="small"
                        autoComplete="off"
                        sx={inputSx}
                        onChange={(event: any) => setNewEndpoint(event.target.value)}
                    />
                )}
                slotProps={{ listbox: { style: { padding: 0 } } }}
            />
        </TableCell>
        <TableCell align="left">
            <TextField size="small" type="text" fullWidth
                variant="outlined"
                placeholder={t('model.optional')}
                sx={inputSx}
                value={newApiBase}
                onChange={(event: any) => { setNewApiBase(event.target.value); }}
                autoComplete='off'
            />
        </TableCell>
        <TableCell align="left">
            <TextField size="small" type="text" fullWidth
                variant="outlined"
                sx={inputSx}
                value={newApiVersion} onChange={(event: any) => { setNewApiVersion(event.target.value); }}
                autoComplete='off'
                placeholder={t('model.optional')}
            />
        </TableCell>
        <TableCell align="left">
            {renderAddButton()}
        </TableCell>
        <TableCell align="right">
            <Tooltip title={t('model.clear')}>
                <IconButton size="small" sx={{ p: 0.25 }} onClick={(event) => { event.stopPropagation(); resetNewModelFields(); }}>
                    <ClearIcon sx={{ fontSize: 14 }} />
                </IconButton>
            </Tooltip>
        </TableCell>
    </TableRow>;

    let newModelEntry = shouldShowDeepSeekEntry
        ? deepSeekModelEntry
        : shouldShowGenericCustomEntry
            ? genericModelEntry
            : null;
    const isDeepSeekUserModel = (model: ModelConfig) => (
        shouldShowDeepSeekEntry
        && deepSeekModels.includes(model.model)
        && (model.api_base || '').replace(/\/$/, '') === deepSeekApiBase
    );
    const visibleUserModels = shouldShowDeepSeekEntry
        ? models.filter(isDeepSeekUserModel)
        : models;

    /** Render a single model row. isGlobal controls delete button and key display. */
    const renderModelRow = (model: ModelConfig, isGlobal: boolean) => {
        const status = getStatus(model.id);
        // Server-configured models in 'unknown' are trusted by default and
        // displayed as "server configured" instead of an untested "Test" row.
        const serverConfigured = isGlobal && status === 'unknown';

        const statusIcon =
            serverConfigured     ? <CheckCircleOutlineIcon color="info" sx={{ fontSize: 16 }} /> :
            status === 'unknown' ? <HelpOutlineIcon sx={{ fontSize: 16, color: 'text.disabled' }} /> :
            status === 'testing' ? <CircularProgress size={14} /> :
            status === 'ok'      ? <CheckCircleOutlineIcon color="success" sx={{ fontSize: 16 }} /> :
                                   <ErrorOutlineIcon color="error" sx={{ fontSize: 16 }} />;

        let message = t('model.modelReadyMessage');
        if (serverConfigured) {
            message = t('model.configuredMessage', 'Server configured, click to verify connectivity');
        } else if (status === 'unknown') {
            message = t('model.clickToTestModel');
        } else if (status === 'error') {
            const rawMessage = testedModels.find(tm => tm.id === model.id)?.message || t('model.unknownError');
            message = t('model.errorMessage', { message: decodeHtmlEntities(rawMessage) });
        }

        // Selectable when verified ('ok'), or when it's a server-configured
        // model in 'unknown' state (trusted by default, no test required).
        const selectable = status === 'ok' || serverConfigured;
        const isSelected = tempSelectedModelId === model.id;

        return (
            <React.Fragment key={model.id}>
                <TableRow
                    sx={{
                        cursor: selectable ? 'pointer' : 'default',
                        // Don't dim error rows so the Retest button and error message remain clearly clickable.
                        opacity: selectable || status === 'error' || status === 'testing' ? 1 : 0.5,
                        backgroundColor: isSelected ? alpha(theme.palette.primary.main, 0.04) : 'transparent',
                        outline: isSelected ? `2px solid ${theme.palette.primary.main}` : 'none',
                        outlineOffset: -2,
                        '&:hover': selectable ? { backgroundColor: isSelected ? alpha(theme.palette.primary.main, 0.06) : 'rgba(0,0,0,0.02)' } : {},
                    }}
                    onClick={() => selectable && setTempSelectedModelId(
                        isSelected ? undefined : model.id
                    )}
                >
                    <TableCell align="left">
                        <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
                            <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {model.model}
                            </Box>
                            {isGlobal && (
                                <Tooltip title={t('model.serverManagedTooltip', 'Managed by administrator')}>
                                    <Box
                                        component="span"
                                        sx={{
                                            fontSize: '0.6rem',
                                            lineHeight: 1,
                                            px: 0.5,
                                            py: '2px',
                                            borderRadius: 0.5,
                                            color: 'text.secondary',
                                            border: '1px solid',
                                            borderColor: 'divider',
                                            textTransform: 'lowercase',
                                            letterSpacing: '0.02em',
                                            whiteSpace: 'nowrap',
                                        }}
                                    >
                                        {t('model.serverChip', 'server configured')}
                                    </Box>
                                </Tooltip>
                            )}
                        </Box>
                    </TableCell>
                    <TableCell>
                        {isGlobal
                            ? null
                            : model.api_key
                                ? (showKeys
                                    ? <Box component="span" sx={{ fontSize: '0.5rem', fontFamily: 'monospace', wordBreak: 'break-all', whiteSpace: 'normal', lineHeight: 1.3 }}>{model.api_key}</Box>
                                    : <Box component="span" sx={{ color: 'text.disabled' }}>********</Box>)
                                : <Box component="span" sx={{ color: 'text.disabled' }}>{t('model.none')}</Box>
                        }
                    </TableCell>
                    <TableCell align="left">
                        {isDeepSeekUserModel(model) ? t('model.deepSeekProviderValue') : model.endpoint}
                    </TableCell>
                    <TableCell align="left">
                        {isGlobal
                            ? null
                            : model.api_base
                                ? <Box component="span" sx={{ wordBreak: 'break-all', whiteSpace: 'normal', lineHeight: 1.3 }}>{model.api_base}</Box>
                                : <Box component="span" sx={{ color: 'text.disabled' }}>{t('model.default')}</Box>
                        }
                    </TableCell>
                    <TableCell align="left">
                        {isGlobal
                            ? null
                            : model.api_version
                                ? model.api_version
                                : <Box component="span" sx={{ color: 'text.disabled' }}>{t('model.default')}</Box>
                        }
                    </TableCell>
                    <TableCell align="left" colSpan={isGlobal ? 2 : 1}>
                        <Tooltip title={message}>
                            <Button
                                size="small"
                                color={serverConfigured ? 'info' : status === 'ok' ? 'success' : status === 'error' ? 'error' : status === 'testing' ? 'inherit' : 'warning'}
                                onClick={(e) => { e.stopPropagation(); testModel(model); }}
                                sx={{ p: 0.5, minWidth: 0, textTransform: 'none', fontSize: 'inherit' }}
                                startIcon={statusIcon}
                            >
                                {serverConfigured ? t('model.serverConfigured', 'server configured') :
                                 status === 'ok' ? t('model.ready') :
                                 status === 'error' ? t('model.retest') :
                                 status === 'testing' ? t('model.testing', 'Testing…') :
                                 t('model.test')}
                            </Button>
                        </Tooltip>
                    </TableCell>
                    {!isGlobal && (
                        <TableCell align="right">
                            <Tooltip title={t('model.removeModel')}>
                                <IconButton
                                    size="small"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        dispatch(dfActions.removeModel(model.id));
                                        if (tempSelectedModelId === model.id) setTempSelectedModelId(undefined);
                                    }}
                                    sx={{ p: 0.25 }}
                                >
                                    <ClearIcon sx={{ fontSize: 14 }} />
                                </IconButton>
                            </Tooltip>
                        </TableCell>
                    )}
                </TableRow>
                {status === 'error' && (
                    <TableRow>
                        <TableCell colSpan={1} />
                        <TableCell colSpan={6} sx={{ borderBottom: 'none' }}>
                            <Box component="span" sx={{ color: 'error.main' }}>
                                {message}
                            </Box>
                        </TableCell>
                    </TableRow>
                )}
            </React.Fragment>
        );
    };

    let modelTable = <TableContainer>
        <Table sx={{
            minWidth: 600,
            tableLayout: 'fixed',
            borderCollapse: 'collapse',
            fontSize: '0.75rem',
            '& th, & td': {
                px: 1, py: 0.75,
                textAlign: 'left',
                borderBottom: 'none',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                fontSize: 'inherit',
            },
            '& th': {
                fontWeight: 600,
                color: 'text.secondary',
                fontSize: '0.7rem',
                bgcolor: 'background.paper',
                borderBottom: '1px solid',
                borderColor: 'divider',
            },
        }} size="small">
            <TableHead>
                <TableRow>
                    <TableCell sx={{ width: '15%' }}>{t('model.model')}</TableCell>
                    <TableCell sx={{ width: '18%' }}>{t('model.apiKey')}</TableCell>
                    <TableCell sx={{ width: '10%' }}>{t('model.provider')}</TableCell>
                    <TableCell sx={{ width: '25%' }}>{t('model.apiBase')}</TableCell>
                    <TableCell sx={{ width: '10%' }}>{t('model.apiVersion')}</TableCell>
                    <TableCell sx={{ width: '12%' }}>{t('model.status')}</TableCell>
                    <TableCell sx={{ width: '5%' }} />
                </TableRow>
            </TableHead>
            <TableBody>
                {/* Server-configured models first, then user-added models. */}
                {globalModels.map(model => renderModelRow(model, true))}
                {visibleUserModels.map(model => renderModelRow(model, false))}
                {newModelEntry}
            </TableBody>
        </Table>
    </TableContainer>

    const allModels = [...globalModels, ...visibleUserModels];

    // A model is "ready" to use when it's been verified ('ok') or when it's a
    // server-configured model in 'unknown' state (trusted by default).
    const isModelReady = (id: string | undefined): boolean => {
        if (!id) return false;
        const status = getStatus(id);
        if (status === 'ok') return true;
        const isGlobal = globalModels.some(m => m.id === id);
        return isGlobal && status === 'unknown';
    };

    let modelNotReady = !isModelReady(tempSelectedModelId);

    let tempModel = allModels.find(m => m.id == tempSelectedModelId);
    let tempModelName = tempModel ? `${tempModel.endpoint}/${tempModel.model}` : t('model.pleaseSelectModel');
    let selectedModelName = allModels.find(m => m.id == selectedModelId)?.model || t('model.unselected');

    const selectedReady = isModelReady(selectedModelId);

    return <>
        <Tooltip title={t('model.selectModel')}>
            <Button sx={{fontSize: "inherit", textTransform: "none"}} variant="text" color={selectedReady ? "primary" : 'warning'} onClick={()=>{setModelDialogOpen(true)}}>
                {selectedReady ? selectedModelName : t('model.selectModels')}
            </Button>
        </Tooltip>
        <Dialog
            maxWidth="lg"
            open={modelDialogOpen}
            onClose={(event, reason) => {
                if (reason !== 'backdropClick') {
                    setModelDialogOpen(false);
                }
            }}
        >
            <DialogTitle sx={{display: "flex",  alignItems: "center"}}>{t('model.selectModel')}</DialogTitle>
            <DialogContent >
            <Box sx={{
                    display: 'flex',
                    color: 'text.secondary',
                    alignItems: 'flex-start',
                    mb: 2,
                    p: 1.5,
                    backgroundColor: alpha(theme.palette.info.main, 0.08),
                }}>
                    <Box>
                        <Typography variant="caption" component="div" sx={{ lineHeight: 1.6 }}>
                            - {shouldShowDeepSeekEntry ? t('model.deepSeekRestrictedTip') : t('model.recommendedModelTip')}
                        </Typography>
                        <Typography variant="caption" component="div" sx={{ lineHeight: 1.6, mt: 0.5 }}>
                            - {shouldShowDeepSeekEntry
                                ? t('model.deepSeekLocalStorageTip')
                                : <>{t('model.litellmNote').split('.')[0]}. <a href="https://docs.litellm.ai/docs/" target="_blank" rel="noopener noreferrer">{t('model.seeDocs')}</a>. {t('model.openaiProviderTip')}</>}
                        </Typography>
                    </Box>
                </Box>
                {modelTable}

            </DialogContent>
            <DialogActions>
                {!serverConfig.DISABLE_DISPLAY_KEYS && (
                    <FormControlLabel
                        sx={{ marginRight: 'auto', ml: 1 }}
                        control={
                            <Switch
                                size="small"
                                checked={showKeys}
                                onChange={() => setShowKeys(!showKeys)}
                            />
                        }
                        label={
                            <Typography variant="body2" sx={{ fontSize: '0.8rem' }}>
                                {showKeys ? t('model.hideKeys') : t('model.showKeys')}
                            </Typography>
                        }
                    />
                )}
                <Button disabled={modelNotReady} sx={{textTransform: 'none'}}
                    variant={modelNotReady ? 'text' : 'contained'}
                    onClick={()=>{
                        dispatch(dfActions.selectModel(tempSelectedModelId));
                        setModelDialogOpen(false);}}>{t('model.useModel', { modelName: tempModelName })}</Button>
                <Button onClick={()=>{
                    setTempSelectedModelId(selectedModelId);
                    setModelDialogOpen(false);
                }}>{t('model.cancel')}</Button>
            </DialogActions>
        </Dialog>
    </>;
}
