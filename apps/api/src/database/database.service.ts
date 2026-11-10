import { Injectable, OnModuleDestroy } from '@nestjs/common';
import { Pool } from 'pg';
import { env } from '../config/env';

@Injectable()
export class DatabaseService implements OnModuleDestroy {
  private readonly pool: Pool | null = env.DATABASE_URL
    ? new Pool({
        connectionString: env.DATABASE_URL,
        max: env.DATABASE_POOL_MAX,
        connectionTimeoutMillis: env.DATABASE_CONNECTION_TIMEOUT_MS,
        application_name: 'simorgh-meet-api',
      })
    : null;

  isConfigured(): boolean {
    return this.pool !== null;
  }

  async ping(): Promise<boolean> {
    if (!this.pool) return false;
    try {
      await this.pool.query('SELECT 1');
      return true;
    } catch {
      return false;
    }
  }

  async onModuleDestroy(): Promise<void> {
    await this.pool?.end();
  }
}
