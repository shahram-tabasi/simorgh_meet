import { Injectable } from '@nestjs/common';
import { DatabaseService } from '../database/database.service';
import { AuthenticatedIdentity } from '../auth/auth.types';

export interface OrganizationMembershipRow {
  [column: string]: any;
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: 'owner' | 'admin' | 'member';
}

@Injectable()
export class IdentityService {
  constructor(private readonly database: DatabaseService) {}

  async listOrganizations(identity: AuthenticatedIdentity): Promise<OrganizationMembershipRow[]> {
    const result = await this.database.query<OrganizationMembershipRow>(
      `SELECT o.id AS organization_id,
              o.name AS organization_name,
              o.slug AS organization_slug,
              m.role
         FROM users u
         JOIN organization_memberships m ON m.user_id = u.id
         JOIN organizations o ON o.id = m.organization_id
        WHERE u.identity_issuer = $1
          AND u.identity_subject = $2
          AND u.status = 'active'
          AND m.status = 'active'
          AND o.status = 'active'
        ORDER BY o.name ASC`,
      [identity.issuer, identity.subject],
    );
    return result.rows;
  }
}
