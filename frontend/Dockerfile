FROM node:22-alpine AS deps

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci


FROM node:22-alpine AS builder

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# API_BASE_URL is read at request time by lib/api.ts, not inlined at build
# time (it isn't NEXT_PUBLIC_*), so it does not need to be a build arg — the
# same image works against any backend. The build still must not need a live
# backend: every page that fetches is `force-dynamic` for exactly that reason.
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build


FROM node:22-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 1001 -S nodejs && adduser -u 1001 -S nextjs -G nodejs

# The standalone server bundles its own minimal node_modules but deliberately
# omits .next/static/ — it has to be copied in or every static asset 404s at
# runtime. There is no public/ directory in this project (the favicon lives in
# app/), so nothing to copy for it; add that COPY if one is ever introduced.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
