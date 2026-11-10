import {
  CanActivate,
  ExecutionContext,
  Injectable,
  ServiceUnavailableException,
  UnauthorizedException,
} from '@nestjs/common';
import { createRemoteJWKSet, jwtVerify } from 'jose';
import { env } from '../config/env';
import { extractBearerToken } from './bearer-token';
import { AuthenticatedRequest } from './auth.types';

@Injectable()
export class OidcAuthGuard implements CanActivate {
  private readonly jwks: ReturnType<typeof createRemoteJWKSet> | null =
    env.OIDC_JWKS_URL ? createRemoteJWKSet(new URL(env.OIDC_JWKS_URL)) : null;

  async canActivate(context: ExecutionContext): Promise<boolean> {
    if (!this.jwks || !env.OIDC_ISSUER || !env.OIDC_AUDIENCE) {
      throw new ServiceUnavailableException('OIDC authentication is not configured.');
    }

    const request = context.switchToHttp().getRequest<AuthenticatedRequest>();
    const token = extractBearerToken(request.headers.authorization);
    if (!token) throw new UnauthorizedException('A valid Bearer access token is required.');

    try {
      const { payload } = await jwtVerify(token, this.jwks, {
        issuer: env.OIDC_ISSUER,
        audience: env.OIDC_AUDIENCE,
        algorithms: ['RS256'],
        requiredClaims: ['sub', 'iss', 'exp', 'iat'],
      });

      if (typeof payload.sub !== 'string' || typeof payload.iss !== 'string') {
        throw new UnauthorizedException('The access token is missing identity claims.');
      }

      request.auth = {
        issuer: payload.iss,
        subject: payload.sub,
        ...(typeof payload.email === 'string' ? { email: payload.email } : {}),
        ...(typeof payload.name === 'string' ? { name: payload.name } : {}),
      };
      return true;
    } catch {
      throw new UnauthorizedException('The access token is invalid or expired.');
    }
  }
}
