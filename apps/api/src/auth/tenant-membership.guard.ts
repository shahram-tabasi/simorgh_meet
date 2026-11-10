import {
  BadRequestException,
  CanActivate,
  ExecutionContext,
  ForbiddenException,
  Injectable,
} from '@nestjs/common';
import { DatabaseService } from '../database/database.service';
import { AuthenticatedRequest, TenantContext } from './auth.types';

interface MembershipRow {
  [column: string]: any;
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  membership_id: string;
  role: 'owner' | 'admin' | 'member';
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

@Injectable()
export class TenantMembershipGuard implements CanActivate {
  constructor(private readonly database: DatabaseService) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<AuthenticatedRequest>();
    const identity = request.auth;
    const organizationId = request.params.organizationId;

    if (!identity) throw new ForbiddenException('Authenticated identity is required.');
    if (!organizationId || !UUID_PATTERN.test(organizationId)) {
      throw new BadRequestException('A valid organizationId is required.');
    }

    const result = await this.database.query<MembershipRow>(
      `SELECT o.id AS organization_id,
              o.name AS organization_name,
              o.slug AS organization_slug,
              m.id AS membership_id,
              m.role
         FROM users u
         JOIN organization_memberships m ON m.user_id = u.id
         JOIN organizations o ON o.id = m.organization_id
        WHERE u.identity_issuer = $1
          AND u.identity_subject = $2
          AND u.status = 'active'
          AND m.organization_id = $3
          AND m.status = 'active'
          AND o.status = 'active'
        LIMIT 1`,
      [identity.issuer, identity.subject, organizationId],
    );

    const membership = result.rows[0];
    if (!membership) throw new ForbiddenException('You are not an active member of this organization.');

    request.tenant = {
      organizationId: membership.organization_id,
      organizationName: membership.organization_name,
      organizationSlug: membership.organization_slug,
      membershipId: membership.membership_id,
      role: membership.role,
    };
    return true;
  }
}
