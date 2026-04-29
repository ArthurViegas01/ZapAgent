/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    typedRoutes: true,
  },
  // The dashboard talks to the API at runtime; no rewrites needed.
};

export default nextConfig;
