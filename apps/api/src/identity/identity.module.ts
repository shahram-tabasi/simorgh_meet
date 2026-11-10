import { Module } from '@nestjs/common';
import { OidcAuthGuard } from '../auth/oidc-auth.guard';
import { TenantMembershipGuard } from '../auth/tenant-membership.guard';
import { IdentityController } from './identity.controller';
import { IdentityService } from './identity.service';
import { OrganizationsController } from '../organizations/organizations.controller';

@Module({
  controllers: [IdentityController, OrganizationsController],
  providers: [IdentityService, OidcAuthGuard, TenantMembershipGuard],
  exports: [OidcAuthGuard, TenantMembershipGuard],
})
export class IdentityModule {}
