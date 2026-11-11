# Simorgh Meet API. Build context: repository root.
FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY package.json ./
COPY apps/api/package.json apps/api/
RUN npm install --workspace @simorgh-meet/api --include-workspace-root=false --no-audit --no-fund
COPY apps/api apps/api
RUN npm run build --workspace @simorgh-meet/api \
 && npm prune --omit=dev --workspace @simorgh-meet/api

FROM node:22-bookworm-slim
ENV NODE_ENV=production
WORKDIR /app/apps/api
COPY --from=build /app/node_modules /app/node_modules
COPY --from=build /app/apps/api/dist ./dist
COPY --from=build /app/apps/api/package.json ./package.json
COPY apps/api/migrations ./migrations
USER node
EXPOSE 8080
# Migrations are idempotent (checksummed, advisory-locked); run them before serving.
CMD ["sh", "-c", "node dist/database/migrate.js && exec node dist/main.js"]
