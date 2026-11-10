import { Controller, Get, Req, UseGuards } from '@nestjs/common';
import { OidcAuthGuard } from '../auth/oidc-auth.guard';
import { AuthenticatedRequest } from '../auth/auth.types';
import { IdentityService } from './identity.service';

@Controller('me')
@UseGuards(OidcAuthGuard)
export class IdentityController {
  constructor(private readonly identity: IdentityService) {}

  @Get('organizations')
  organizations(@Req() request: AuthenticatedRequest) {
    return this.identity.listOrganizations(request.auth!);
  }
}
