import { describe, expect, it } from 'vitest';

import { shouldAutoMarkRead } from './autoMarkRead';

const base = {
    roomId: 7,
    lastMessageId: 42,
    companyArchived: false,
    permissionsLoading: false,
};

describe('shouldAutoMarkRead', () => {
    it('marks the open chat read in an active company', () => {
        expect(shouldAutoMarkRead(base)).toBe(true);
    });

    it('does not mark read on an archived company — the POST would 403 and toast', () => {
        expect(shouldAutoMarkRead({ ...base, companyArchived: true })).toBe(false);
    });

    it('waits for permissions: archived or not is unknown yet', () => {
        expect(shouldAutoMarkRead({ ...base, permissionsLoading: true })).toBe(false);
    });

    it('needs both a room and a last message', () => {
        expect(shouldAutoMarkRead({ ...base, roomId: null })).toBe(false);
        expect(shouldAutoMarkRead({ ...base, lastMessageId: null })).toBe(false);
    });
});
