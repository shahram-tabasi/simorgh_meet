import { Controller, Get, ServiceUnavailableException } from '@nestjs/common';
import { DatabaseService } from './database/database.service';

@Controller('health')
export class HealthController {
  constructor(private readonly database: DatabaseService) {}

  @Get('live')
  live() {
    return { status: 'ok', service: 'simorgh-meet-api' };
  }

  @Get('ready')
  async ready() {
    if (!this.database.isConfigured() || !(await this.database.ping())) {
      throw new ServiceUnavailableException({
        status: 'not_ready',
        checks: { database: 'unavailable' },
      });
    }

    return {
      status: 'ready',
      checks: { database: 'ok' },
    };
  }
}
