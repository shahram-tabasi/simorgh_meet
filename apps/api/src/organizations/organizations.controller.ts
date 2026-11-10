import { Controller, Get, Req, UseGuards } from '@nestjs/common';
import { OidcAuthGuard } from '../auth/oidc-auth.guard';
import { TenantMembershipGuard } from '../auth/tenant-membership.guard';
import { AuthenticatedRequest } from '../auth/auth.types';

@Controller('organizations/:organizationId')
@UseGuards(OidcAuthGuard, TenantMembershipGuard)
export class OrganizationsController {
  @Get('context')
  context(@Req() request: AuthenticatedRequest) {
    return request.tenant;
  }
}
