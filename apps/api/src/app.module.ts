import { Module } from '@nestjs/common';
import { DatabaseModule } from './database/database.module';
import { HealthController } from './health.controller';
import { IdentityModule } from './identity/identity.module';

@Module({
  imports: [DatabaseModule, IdentityModule],
  controllers: [HealthController],
})
export class AppModule {}
