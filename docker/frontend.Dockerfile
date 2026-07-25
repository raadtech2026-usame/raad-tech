# RAAD Web Dashboard — container image (ADR-0013: docs/architecture/adr/
# 0013-platform-dockerization.md).
#
# Build context is `frontend/` itself. Four stages, selected via Compose `build.target`:
#   deps  — installs node_modules once, shared by dev/build
#   dev   — Vite dev server w/ HMR (docker-compose.yml's default target; docker-compose.dev.yml
#           additionally bind-mounts source over this stage's own COPY for live editing)
#   build — `npm run build`; VITE_* are Vite build-time constants (inlined into the bundle by
#           esbuild/rollup), so they must arrive as build ARGs, not container-runtime env vars
#   prod  — nginx:alpine serving the built dist/ (docker-compose.prod.yml selects this target).
#           Ships nginx's stock default.conf; docker-compose.prod.yml bind-mounts
#           infrastructure/nginx/conf.d/frontend.conf over it for SPA try_files fallback — kept
#           as a runtime mount, not baked in here, so this Dockerfile's build context never needs
#           to reach outside frontend/.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM deps AS build
COPY . .
ARG VITE_API_BASE_URL
ARG VITE_WS_BASE_URL
# Docker's build linter flags ARG/ENV containing "TOKEN" as a possible leaked secret — not
# applicable here: a Mapbox GL JS access token is a public, domain/rate-limit-restricted client
# key that ships inside the browser bundle by design (frontend/.env.example's own stance), not a
# server-side credential.
ARG VITE_MAPBOX_ACCESS_TOKEN
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_WS_BASE_URL=$VITE_WS_BASE_URL \
    VITE_MAPBOX_ACCESS_TOKEN=$VITE_MAPBOX_ACCESS_TOKEN
RUN npm run build

FROM nginx:1.27-alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
