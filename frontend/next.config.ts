import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits .next/standalone with a self-contained server.js and only the
  // node_modules actually reached at runtime, so the deployed image doesn't
  // need a full `npm install`. Note the standalone server does NOT bundle
  // `public/` or `.next/static/` — the Dockerfile copies those in explicitly
  // (per next.config output docs), otherwise every asset 404s.
  output: "standalone",
};

export default nextConfig;
