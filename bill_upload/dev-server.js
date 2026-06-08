/**
 * Local dev server — no Vercel login required.
 * Uses Bun.serve so multipart uploads work via native FormData parsing.
 *
 * Usage: bun run dev
 */

const path = require('path');

const validateToken = require('./api/validate-token');
const upload = require('./api/upload');

const PUBLIC = path.join(__dirname, 'public');
const PORT = Number(process.env.PORT) || 3000;

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.ico': 'image/x-icon',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
};

/** Run a Vercel-style handler and return a Fetch Response. */
function runHandler(handler, req, extras = {}) {
  return new Promise((resolve) => {
    const mockReq = { method: req.method, ...extras };
    const headers = {};
    let statusCode = 200;
    let settled = false;

    const mockRes = {
      setHeader(name, value) {
        headers[name] = value;
        return mockRes;
      },
      status(code) {
        statusCode = code;
        return mockRes;
      },
      json(body) {
        settled = true;
        resolve(
          Response.json(body, {
            status: statusCode,
            headers,
          }),
        );
      },
      end(data) {
        settled = true;
        resolve(new Response(data ?? null, { status: statusCode, headers }));
      },
    };

    Promise.resolve(handler(mockReq, mockRes)).then(() => {
      if (!settled) {
        resolve(new Response(null, { status: statusCode, headers }));
      }
    });
  });
}

Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);

    if (url.pathname === '/api/validate-token') {
      return runHandler(validateToken, req, {
        query: Object.fromEntries(url.searchParams),
      });
    }

    if (url.pathname === '/api/upload') {
      const formData = req.method === 'POST' ? await req.formData() : null;
      return runHandler(upload, req, { _formData: formData });
    }

    const rel = url.pathname === '/' ? '/index.html' : url.pathname;
    const filePath = path.normalize(path.join(PUBLIC, rel));
    if (!filePath.startsWith(PUBLIC)) {
      return new Response('Forbidden', { status: 403 });
    }

    const file = Bun.file(filePath);
    if (!(await file.exists())) {
      return new Response('Not found', { status: 404 });
    }

    const ext = path.extname(filePath);
    return new Response(file, {
      headers: MIME[ext] ? { 'Content-Type': MIME[ext] } : {},
    });
  },
});

console.log(`Lumi bill upload — http://localhost:${PORT}`);
console.log(`Test with: http://localhost:${PORT}/?token=YOUR_TOKEN`);
