FROM node:22-alpine AS deps
WORKDIR /repo/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /repo
COPY packages/contracts packages/contracts
COPY apps/web apps/web
COPY --from=deps /repo/apps/web/node_modules apps/web/node_modules
WORKDIR /repo/apps/web
ENV NEXT_TELEMETRY_DISABLED=1
ARG API_INTERNAL_URL=http://api:8400
ENV API_INTERNAL_URL=$API_INTERNAL_URL
RUN npx next build

FROM node:22-alpine
WORKDIR /repo/apps/web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /repo/apps/web ./
USER node
EXPOSE 3400
CMD ["sh", "-c", "npx next start -H 0.0.0.0 -p ${PORT:-3400}"]
