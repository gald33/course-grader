/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  // Same-origin proxy to the backend. The student review page (/r/<token>)
  // calls /api/r/... through this, so exposing only the frontend port (e.g.
  // through a tunnel) is enough for students on their phones.
  async rewrites() {
    const backend = process.env.BACKEND_INTERNAL_URL || 'http://localhost:8000';
    return [{ source: '/api/:path*', destination: `${backend}/api/:path*` }];
  }
};

export default nextConfig;
