import React, { useEffect, useMemo, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    FormControl,
    InputLabel,
    MenuItem,
    Select,
    Stack,
    TextField,
    Typography,
    type SelectChangeEvent,
} from '@mui/material';
import AutoFixHighOutlinedIcon from '@mui/icons-material/AutoFixHighOutlined';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import PlaylistAddOutlinedIcon from '@mui/icons-material/PlaylistAddOutlined';
import type { TFunction } from 'i18next';

import type {
    AnalysisGoal,
    ClarificationQuestion,
    ColumnProfile,
    GoalCandidate,
    GoalFilter,
    GoalType,
    InsightError,
    IntentRequest,
} from '../types';

const MVP_GOAL_TYPES: GoalType[] = [
    'trend_analysis',
    'comparison',
    'driver_analysis',
    'segment_analysis',
    'distribution_analysis',
    'data_quality_review',
];

type PanelMode = 'intent' | 'custom';

type EditorKind = 'candidate' | 'custom';

interface GoalEditorForm {
    title: string;
    goalType: GoalType;
    targetMetric: string;
    dimensions: string[];
    timeColumn: string;
    description: string;
    sourceCandidateId?: string;
    filters: GoalFilter[];
}

function toCandidateForm(candidate: GoalCandidate): GoalEditorForm {
    return {
        title: candidate.title,
        goalType: candidate.goal_type,
        targetMetric: candidate.target_metric || '',
        dimensions: [...candidate.dimensions],
        timeColumn: candidate.time_column || '',
        description: candidate.description,
        sourceCandidateId: candidate.id,
        filters: candidate.filters,
    };
}

function toCustomForm(goal: AnalysisGoal | null): GoalEditorForm {
    return {
        title: goal?.title || '',
        goalType: goal?.goal_type || 'driver_analysis',
        targetMetric: goal?.target_metric || goal?.target_column || '',
        dimensions: goal?.dimensions ? [...goal.dimensions] : [],
        timeColumn: goal?.time_column || '',
        description: goal?.description || '',
        filters: goal?.filters ? [...goal.filters] : [],
    };
}

function formatFilters(filters: GoalFilter[]): string {
    if (!filters.length) return '-';
    return filters
        .map((goalFilter) => {
            const suffix = goalFilter.value == null ? '' : ` ${String(goalFilter.value)}`;
            return `${goalFilter.column} ${goalFilter.operator}${suffix}`;
        })
        .join(', ');
}

function questionKey(question: ClarificationQuestion, index: number): string {
    return question.text_code || `${question.text}-${index}`;
}

function translateClarificationText(t: TFunction, code: string | null | undefined, fallback: string): string {
    if (!code) return fallback;
    const translated = t(code, { defaultValue: fallback });
    return translated && translated !== code ? String(translated) : fallback;
}

export interface GoalConfirmationPanelProps {
    datasetId: string;
    versionId: string;
    columns: ColumnProfile[];
    status: 'idle' | 'loading' | 'generating' | 'confirming' | 'ready' | 'error';
    error: InsightError | null;
    activeGoal: AnalysisGoal | null;
    intent: IntentRequest | null;
    goalCandidates: GoalCandidate[];
    questions: ClarificationQuestion[];
    mode: PanelMode;
    t: TFunction;
    onGenerateIntent: (userInput: string) => void;
    onConfirmGoal: (request: {
        datasetId: string;
        datasetVersionId: string;
        sourceCandidateId?: string;
        intentId?: string;
        title?: string;
        goalType?: GoalType;
        targetMetric?: string | null;
        dimensions?: string[];
        timeColumn?: string | null;
        filters?: GoalFilter[];
        description?: string;
    }) => void;
    onCancel?: () => void;
}

export function GoalConfirmationPanel({
    datasetId,
    versionId,
    columns,
    status,
    error,
    activeGoal,
    intent,
    goalCandidates,
    questions,
    mode,
    t,
    onGenerateIntent,
    onConfirmGoal,
    onCancel,
}: GoalConfirmationPanelProps) {
    const [userInput, setUserInput] = useState(intent?.user_input || '');
    const [editorKind, setEditorKind] = useState<EditorKind | null>(mode === 'custom' ? 'custom' : null);
    const [editorForm, setEditorForm] = useState<GoalEditorForm>(mode === 'custom' ? toCustomForm(activeGoal) : toCustomForm(null));

    useEffect(() => {
        setUserInput(intent?.user_input || '');
    }, [intent?.id, intent?.user_input]);

    useEffect(() => {
        if (mode === 'custom') {
            setEditorKind('custom');
            setEditorForm(toCustomForm(activeGoal));
            return;
        }
        setEditorKind(null);
        setEditorForm(toCustomForm(null));
    }, [activeGoal, mode]);

    const availableColumns = useMemo(
        () => columns.map((column) => column.name),
        [columns],
    );

    const generating = status === 'generating';
    const confirming = status === 'confirming';
    const editing = editorKind !== null;
    const clarificationRequired = intent?.status === 'awaiting_clarification';

    const openCandidateEditor = (candidate: GoalCandidate) => {
        setEditorKind('candidate');
        setEditorForm(toCandidateForm(candidate));
    };

    const openCustomEditor = () => {
        setEditorKind('custom');
        setEditorForm(toCustomForm(activeGoal));
    };

    const closeEditor = () => {
        if (mode === 'custom' && onCancel) {
            onCancel();
            return;
        }
        setEditorKind(null);
        setEditorForm(toCustomForm(activeGoal));
    };

    const submitGoal = () => {
        onConfirmGoal({
            datasetId,
            datasetVersionId: versionId,
            sourceCandidateId: editorForm.sourceCandidateId,
            intentId: intent?.id,
            title: editorForm.title.trim() || undefined,
            goalType: editorForm.goalType,
            targetMetric: editorForm.targetMetric || null,
            dimensions: editorForm.dimensions,
            timeColumn: editorForm.timeColumn || null,
            filters: editorForm.filters,
            description: editorForm.description,
        });
    };

    const disabledGenerate = !userInput.trim() || generating || confirming;
    const disabledConfirm = !editorForm.title.trim() || confirming;

    return (
        <Stack spacing={2}>
            <Card variant="outlined">
                <CardContent>
                    <Stack spacing={1.5}>
                        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                            {t('insight.goal.panelTitle')}
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                            {t('insight.goal.panelBody')}
                        </Typography>
                        <TextField
                            label={t('insight.goal.userInputLabel')}
                            value={userInput}
                            onChange={(event) => setUserInput(event.target.value)}
                            multiline
                            minRows={2}
                        />
                        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
                            <Button
                                variant="contained"
                                startIcon={<AutoFixHighOutlinedIcon />}
                                disabled={disabledGenerate}
                                onClick={() => onGenerateIntent(userInput.trim())}
                            >
                                {generating ? t('insight.goal.generating') : t('insight.goal.generate')}
                            </Button>
                            <Button
                                variant="outlined"
                                startIcon={<PlaylistAddOutlinedIcon />}
                                disabled={confirming}
                                onClick={openCustomEditor}
                            >
                                {t('insight.goal.newCustomGoal')}
                            </Button>
                            {onCancel ? (
                                <Button variant="text" disabled={confirming} onClick={onCancel}>
                                    {t('insight.goal.cancel')}
                                </Button>
                            ) : null}
                        </Stack>
                    </Stack>
                </CardContent>
            </Card>

            {error ? (
                <Alert severity="error" variant="outlined">
                    {error.message}
                </Alert>
            ) : null}

            {questions.length ? (
                <Card variant="outlined">
                    <CardContent>
                        <Stack spacing={1}>
                            {clarificationRequired ? (
                                <Alert severity="warning" variant="outlined">
                                    {t('insight.goal.clarificationRequired')}
                                </Alert>
                            ) : null}
                            <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                                {t('insight.goal.questionsTitle')}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                {t('insight.goal.questionsHint')}
                            </Typography>
                            {questions.map((question, index) => (
                                <Box key={questionKey(question, index)}>
                                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                        {translateClarificationText(t, question.text_code, question.text)}
                                    </Typography>
                                    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 0.75 }}>
                                        {question.options.map((option, optionIndex) => (
                                            <Chip key={`${questionKey(question, index)}-${optionIndex}`} size="small" label={translateClarificationText(t, option.label_code, option.label)} />
                                        ))}
                                    </Stack>
                                </Box>
                            ))}
                        </Stack>
                    </CardContent>
                </Card>
            ) : null}

            {editing ? (
                <Card variant="outlined">
                    <CardContent>
                        <Stack spacing={1.5}>
                            <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                                {t(editorKind === 'custom' ? 'insight.goal.editor.customTitle' : 'insight.goal.editor.candidateTitle')}
                            </Typography>
                            <TextField
                                label={t('insight.goal.fields.title')}
                                value={editorForm.title}
                                onChange={(event) => setEditorForm((current) => ({ ...current, title: event.target.value }))}
                            />
                            <FormControl fullWidth>
                                <InputLabel>{t('insight.goal.fields.goalType')}</InputLabel>
                                <Select
                                    value={editorForm.goalType}
                                    label={t('insight.goal.fields.goalType')}
                                    onChange={(event) => setEditorForm((current) => ({ ...current, goalType: event.target.value as GoalType }))}
                                >
                                    {MVP_GOAL_TYPES.map((goalType) => (
                                        <MenuItem key={goalType} value={goalType}>
                                            {t(`insight.goal.types.${goalType}`)}
                                        </MenuItem>
                                    ))}
                                </Select>
                            </FormControl>
                            <FormControl fullWidth>
                                <InputLabel>{t('insight.goal.fields.targetMetric')}</InputLabel>
                                <Select
                                    value={editorForm.targetMetric}
                                    label={t('insight.goal.fields.targetMetric')}
                                    onChange={(event) => setEditorForm((current) => ({ ...current, targetMetric: event.target.value }))}
                                >
                                    <MenuItem value="">-</MenuItem>
                                    {availableColumns.map((columnName) => (
                                        <MenuItem key={columnName} value={columnName}>{columnName}</MenuItem>
                                    ))}
                                </Select>
                            </FormControl>
                            <FormControl fullWidth>
                                <InputLabel>{t('insight.goal.fields.timeColumn')}</InputLabel>
                                <Select
                                    value={editorForm.timeColumn}
                                    label={t('insight.goal.fields.timeColumn')}
                                    onChange={(event) => setEditorForm((current) => ({ ...current, timeColumn: event.target.value }))}
                                >
                                    <MenuItem value="">-</MenuItem>
                                    {availableColumns.map((columnName) => (
                                        <MenuItem key={columnName} value={columnName}>{columnName}</MenuItem>
                                    ))}
                                </Select>
                            </FormControl>
                            <FormControl fullWidth>
                                <InputLabel>{t('insight.goal.fields.dimensions')}</InputLabel>
                                <Select
                                    multiple
                                    value={editorForm.dimensions}
                                    label={t('insight.goal.fields.dimensions')}
                                    renderValue={(selected) => (selected as string[]).join(', ') || '-'}
                                    onChange={(event: SelectChangeEvent<string[]>) => {
                                        const value = event.target.value;
                                        setEditorForm((current) => ({
                                            ...current,
                                            dimensions: typeof value === 'string' ? value.split(',') : value,
                                        }));
                                    }}
                                >
                                    {availableColumns.map((columnName) => (
                                        <MenuItem key={columnName} value={columnName}>{columnName}</MenuItem>
                                    ))}
                                </Select>
                            </FormControl>
                            <TextField
                                label={t('insight.goal.fields.description')}
                                value={editorForm.description}
                                onChange={(event) => setEditorForm((current) => ({ ...current, description: event.target.value }))}
                                multiline
                                minRows={2}
                            />
                            <Alert severity="info" variant="outlined">
                                <Typography variant="body2">
                                    <strong>{t('insight.goal.fields.filters')}:</strong> {formatFilters(editorForm.filters)}
                                </Typography>
                                <Typography variant="caption" sx={{ display: 'block', mt: 0.75 }}>
                                    {t('insight.goal.filtersReadonly')}
                                </Typography>
                            </Alert>
                            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
                                <Button variant="contained" disabled={disabledConfirm} onClick={submitGoal}>
                                    {confirming ? t('insight.goal.confirming') : t('insight.goal.confirmGoal')}
                                </Button>
                                <Button variant="text" disabled={confirming} onClick={closeEditor}>
                                    {t('insight.goal.cancel')}
                                </Button>
                            </Stack>
                        </Stack>
                    </CardContent>
                </Card>
            ) : null}

            <Stack spacing={1.5}>
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                    {t('insight.goal.candidatesTitle')}
                </Typography>
                {goalCandidates.length ? goalCandidates.map((candidate) => (
                    <Card key={candidate.id} variant="outlined">
                        <CardContent>
                            <Stack spacing={1.25}>
                                <Stack
                                    direction={{ xs: 'column', sm: 'row' }}
                                    spacing={1}
                                    justifyContent="space-between"
                                    alignItems={{ xs: 'flex-start', sm: 'center' }}
                                >
                                    <Stack spacing={0.5}>
                                        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                                            {candidate.title}
                                        </Typography>
                                        <Typography variant="body2" color="text.secondary">
                                            {candidate.description || t('insight.goal.candidateNoDescription')}
                                        </Typography>
                                    </Stack>
                                    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                                        <Chip size="small" label={t(`insight.goal.types.${candidate.goal_type}`)} />
                                        <Chip size="small" variant="outlined" label={t('insight.goal.confidence', { value: Math.round(candidate.confidence * 100) })} />
                                    </Stack>
                                </Stack>
                                <Stack spacing={0.5}>
                                    <Typography variant="body2"><strong>{t('insight.goal.fields.targetMetric')}:</strong> {candidate.target_metric || '-'}</Typography>
                                    <Typography variant="body2"><strong>{t('insight.goal.fields.timeColumn')}:</strong> {candidate.time_column || '-'}</Typography>
                                    <Typography variant="body2"><strong>{t('insight.goal.fields.dimensions')}:</strong> {candidate.dimensions.join(', ') || '-'}</Typography>
                                    <Typography variant="body2"><strong>{t('insight.goal.fields.filters')}:</strong> {formatFilters(candidate.filters)}</Typography>
                                </Stack>
                                {candidate.assumptions.length ? (
                                    <Alert severity="info" variant="outlined">
                                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                            {t('insight.goal.assumptions')}
                                        </Typography>
                                        <Typography variant="body2">
                                            {candidate.assumptions.join(' ')}
                                        </Typography>
                                    </Alert>
                                ) : null}
                                {candidate.missing_information.length ? (
                                    <Alert severity="warning" variant="outlined">
                                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                            {t('insight.goal.missingInformation')}
                                        </Typography>
                                        <Typography variant="body2">
                                            {candidate.missing_information.join(' ')}
                                        </Typography>
                                    </Alert>
                                ) : null}
                                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
                                    <Button
                                        variant="contained"
                                        disabled={confirming || clarificationRequired}
                                        onClick={() => onConfirmGoal({
                                            datasetId,
                                            datasetVersionId: versionId,
                                            sourceCandidateId: candidate.id,
                                        })}
                                    >
                                        {t('insight.goal.useCandidate')}
                                    </Button>
                                    <Button
                                        variant="outlined"
                                        startIcon={<EditOutlinedIcon />}
                                        disabled={confirming || clarificationRequired}
                                        onClick={() => openCandidateEditor(candidate)}
                                    >
                                        {t('insight.goal.editCandidate')}
                                    </Button>
                                </Stack>
                            </Stack>
                        </CardContent>
                    </Card>
                )) : (
                    <Alert severity="info" variant="outlined">
                        {t('insight.goal.candidatesEmpty')}
                    </Alert>
                )}
            </Stack>
        </Stack>
    );
}