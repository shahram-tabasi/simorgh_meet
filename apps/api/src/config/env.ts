import { z } from 'zod';

const envSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  PORT: z.coerce.number().int().min(1).max(65535).default(8080),
  DATABASE_URL: z.string().trim().optional().transform((value) => value || undefined),
  DATABASE_POOL_MAX: z.coerce.number().int().min(1).max(100).default(10),
  DATABASE_CONNECTION_TIMEOUT_MS: z.coerce.number().int().min(250).max(60000).default(5000),
  OIDC_ISSUER: z.string().url().optional(),
  OIDC_AUDIENCE: z.string().trim().min(1).optional(),
  OIDC_JWKS_URL: z.string().url().optional(),
}).superRefine((value, context) => {
  const configured = [value.OIDC_ISSUER, value.OIDC_AUDIENCE, value.OIDC_JWKS_URL]
    .filter(Boolean).length;
  if (configured !== 0 && configured !== 3) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: 'OIDC_ISSUER, OIDC_AUDIENCE, and OIDC_JWKS_URL must be configured together.',
    });
  }
});

const parsed = envSchema.safeParse(process.env);

if (!parsed.success) {
  throw new Error(`Invalid environment configuration: ${parsed.error.issues
    .map((issue) => `${issue.path.join('.')}: ${issue.message}`)
    .join('; ')}`);
}

export const env = Object.freeze(parsed.data);
