import 'reflect-metadata';
import { createHash } from 'node:crypto';
import { readdir, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { Pool, PoolClient } from 'pg';
import { env } from '../config/env';

interface Migration {
  name: string;
  sql: string;
  checksum: string;
}

const MIGRATION_LOCK_ID = '1397312837';

async function loadMigrations(): Promise<Migration[]> {
  const directory = resolve(process.cwd(), 'migrations');
  const names = (await readdir(directory))
    .filter((name) => /^\d{3}_[a-z0-9_]+\.sql$/.test(name))
    .sort();

  const migrations: Migration[] = [];
  for (const name of names) {
    const sql = await readFile(resolve(directory, name), 'utf8');
    migrations.push({
      name,
      sql,
      checksum: createHash('sha256').update(sql).digest('hex'),
    });
  }
  return migrations;
}

async function applyMigration(client: PoolClient, migration: Migration): Promise<void> {
  await client.query('BEGIN');
  try {
    const existing = await client.query<{ checksum: string }>(
      'SELECT checksum FROM public.schema_migrations WHERE name = $1',
      [migration.name],
    );

    if (existing.rowCount) {
      if (existing.rows[0].checksum !== migration.checksum) {
        throw new Error(`Applied migration was modified: ${migration.name}`);
      }
      await client.query('COMMIT');
      return;
    }

    await client.query(migration.sql);
    await client.query(
      'INSERT INTO public.schema_migrations (name, checksum) VALUES ($1, $2)',
      [migration.name, migration.checksum],
    );
    await client.query('COMMIT');
    process.stdout.write(`Applied migration: ${migration.name}\n`);
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  }
}

async function main(): Promise<void> {
  if (!env.DATABASE_URL) {
    throw new Error('DATABASE_URL is required to run database migrations.');
  }

  const pool = new Pool({
    connectionString: env.DATABASE_URL,
    max: 1,
    connectionTimeoutMillis: env.DATABASE_CONNECTION_TIMEOUT_MS,
    application_name: 'simorgh-meet-migrations',
  });
  const client = await pool.connect();

  try {
    await client.query(`SELECT pg_advisory_lock(${MIGRATION_LOCK_ID})`);
    await client.query(`
      CREATE TABLE IF NOT EXISTS public.schema_migrations (
        name text PRIMARY KEY,
        checksum char(64) NOT NULL,
        applied_at timestamptz NOT NULL DEFAULT now()
      )
    `);

    for (const migration of await loadMigrations()) {
      await applyMigration(client, migration);
    }
  } finally {
    try {
      await client.query(`SELECT pg_advisory_unlock(${MIGRATION_LOCK_ID})`);
    } finally {
      client.release();
      await pool.end();
    }
  }
}

void main().catch((error: unknown) => {
  process.stderr.write(
    `Simorgh Meet migrations failed: ${error instanceof Error ? error.message : String(error)}\n`,
  );
  process.exitCode = 1;
});
