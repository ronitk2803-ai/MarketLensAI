import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // `standalone` emits .next/standalone with a self-contained server.js and
  // only the node_modules reached at runtime, so the Docker image
  // (frontend/Dockerfile, docker-compose.prod.yml) doesn't need a full
  // `npm install`. The standalone server does NOT bundle `public/` or
  // `.next/static/` — the Dockerfile copies those in explicitly, otherwise
  // every asset 404s.
  //
  // But standalone also suppresses the `*.nft.json` trace files that
  // Vercel's build pipeline expects, so a Vercel build dies with
  // `ENOENT: next-server.js.nft.json`. Vercel sets VERCEL=1 during builds —
  // there, drop standalone and let Vercel use its native output.
  output: process.env.VERCEL ? undefined : "standalone",
};

export default nextConfig;
