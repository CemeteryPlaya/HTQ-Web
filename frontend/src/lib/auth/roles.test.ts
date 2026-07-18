import { describe, expect, it } from 'vitest';

import {
  hasEmployeeRole,
  hasEmployeeTaskAccess,
  usesEmployeeTaskExperience,
} from './roles';
import type { UserProfile } from '@/types/userProfile';

const profile = (roles: string[]): UserProfile => ({
  id: '1',
  email: 'user@example.com',
  display_name: 'User',
  bio: '',
  roles,
  settings: {},
  created_at: '',
  updated_at: '',
});

describe('role helpers', () => {
  it('treats explicit employee as task employee', () => {
    const employee = profile(['employee']);

    expect(hasEmployeeRole(employee.roles)).toBe(true);
    expect(hasEmployeeTaskAccess(employee)).toBe(true);
    expect(usesEmployeeTaskExperience(employee)).toBe(true);
  });

  it('treats legacy user as task employee', () => {
    const employee = profile(['user']);

    expect(hasEmployeeRole(employee.roles)).toBe(true);
    expect(hasEmployeeTaskAccess(employee)).toBe(true);
    expect(usesEmployeeTaskExperience(employee)).toBe(true);
  });

  it('keeps staff/admin on elevated task experience', () => {
    const staff = profile(['staff']);

    expect(hasEmployeeTaskAccess(staff)).toBe(true);
    expect(usesEmployeeTaskExperience(staff)).toBe(false);
  });
});
