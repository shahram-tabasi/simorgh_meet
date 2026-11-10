import { Request } from 'express';

export interface AuthenticatedIdentity {
  issuer: string;
  subject: string;
  email?: string;
  name?: string;
}

export interface TenantContext {
  organizationId: string;
  organizationName: string;
  organizationSlug: string;
  membershipId: string;
  role: 'owner' | 'admin' | 'member';
}

export interface AuthenticatedRequest extends Request {
  auth?: AuthenticatedIdentity;
  tenant?: TenantContext;
}
