/**
 * Tests for getAccessToken token refresh behavior.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockGetUser = vi.fn();
const mockSigninSilent = vi.fn();
const mockAddSilentRenewError = vi.fn();

vi.mock('oidc-client-ts', () => ({
    UserManager: vi.fn(function MockUserManager() {
        return {
            getUser: mockGetUser,
            signinSilent: mockSigninSilent,
            signinRedirect: vi.fn(),
            events: {
                addSilentRenewError: mockAddSilentRenewError,
            },
        };
    }),
    WebStorageStateStore: vi.fn(),
    User: class {},
}));

import { _resetForTesting, getAccessToken } from '../../../../src/app/oidcConfig';

describe('getAccessToken', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        _resetForTesting();
        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue(
                new Response(
                    JSON.stringify({
                        status: 'success',
                        data: {
                            action: 'frontend',
                            oidc: {
                                authority: 'https://sso.example.test',
                                clientId: 'client-1',
                                scopes: 'openid profile email',
                            },
                        },
                    }),
                    {
                        status: 200,
                        headers: { 'Content-Type': 'application/json' },
                    },
                ),
            ),
        );
    });

    afterEach(() => {
        _resetForTesting();
        vi.unstubAllGlobals();
    });

    it('returns token when user exists and not expired', async () => {
        mockGetUser.mockResolvedValue({ expired: false, access_token: 'fresh-token' });

        const token = await getAccessToken();

        expect(token).toBe('fresh-token');
        expect(mockSigninSilent).not.toHaveBeenCalled();
    });

    it('returns null when no user stored', async () => {
        mockGetUser.mockResolvedValue(null);

        const token = await getAccessToken();

        expect(token).toBeNull();
        expect(mockSigninSilent).not.toHaveBeenCalled();
    });

    it('calls signinSilent when token is expired and returns refreshed token', async () => {
        mockGetUser.mockResolvedValue({ expired: true, access_token: 'old-token' });
        mockSigninSilent.mockResolvedValue({ expired: false, access_token: 'refreshed-token' });

        const token = await getAccessToken();

        expect(token).toBe('refreshed-token');
        expect(mockSigninSilent).toHaveBeenCalledOnce();
    });

    it('returns null when token is expired and signinSilent fails', async () => {
        mockGetUser.mockResolvedValue({ expired: true, access_token: 'old-token' });
        mockSigninSilent.mockRejectedValue(new Error('refresh failed'));

        const token = await getAccessToken();

        expect(token).toBeNull();
        expect(mockSigninSilent).toHaveBeenCalledOnce();
    });

    it('returns null when token is expired and signinSilent returns null', async () => {
        mockGetUser.mockResolvedValue({ expired: true, access_token: 'old-token' });
        mockSigninSilent.mockResolvedValue(null);

        const token = await getAccessToken();

        expect(token).toBeNull();
    });
});