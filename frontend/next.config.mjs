/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  // Same-origin proxy to the backend. The student review page (/r/<token>)
  // calls /api/r/... through this, so exposing only the frontend port (e.g.
  // through a tunnel) is enough for students on their phones.
  async rewrites() {
    const backend = process.env.BACKEND_INTERNAL_URL || 'http://localhost:8000';
    return [{ source: '/api/:path*', destination: `${backend}/api/:path*` }];
  },
  // Lesson assets (public/lessons/...): a notebook downloads as a file instead
  // of opening as JSON text, and the CSV is served as UTF-8 text.
  async headers() {
    return [
      {
        source: '/lessons/:path*.ipynb',
        headers: [
          { key: 'Content-Type', value: 'application/x-ipynb+json' },
          { key: 'Content-Disposition', value: 'attachment' }
        ]
      },
      {
        source: '/lessons/:path*.csv',
        headers: [{ key: 'Content-Type', value: 'text/csv; charset=utf-8' }]
      }
    ];
  }
};

export default nextConfig;
