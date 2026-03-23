const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const BACKEND_API_KEY = process.env.BACKEND_API_KEY || "";

export async function proxyToBackend(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const url = `${BACKEND_URL}${path}`;
  const headers = new Headers(init.headers);

  if (BACKEND_API_KEY) {
    headers.set("Authorization", `Bearer ${BACKEND_API_KEY}`);
  }

  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers,
    });
  } catch (err) {
    console.error(`[proxy] Backend unreachable: ${url}`, err);
    return new Response(
      JSON.stringify({ detail: "Backend service unavailable" }),
      { status: 502, headers: { "content-type": "application/json" } }
    );
  }

  const responseHeaders = new Headers();
  const passthroughHeaders = [
    "content-type",
    "content-disposition",
    "content-length",
    "cache-control",
  ];
  for (const h of passthroughHeaders) {
    const val = res.headers.get(h);
    if (val) responseHeaders.set(h, val);
  }

  return new Response(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers: responseHeaders,
  });
}
