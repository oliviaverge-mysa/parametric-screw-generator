import { auth } from "@/auth";
import { proxyToBackend } from "@/lib/backend";
import { NextRequest } from "next/server";

export const config = {
  api: { bodyParser: false },
};

function buildBackendPath(params: { path: string[] }, search: string) {
  const joined = `/api/chats/${params.path.join("/")}`;
  return search ? `${joined}${search}` : joined;
}

async function getAuthorName(): Promise<string | undefined> {
  try {
    const session = await auth();
    return session?.user?.name || session?.user?.email?.split("@")[0] || undefined;
  } catch {
    return undefined;
  }
}

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const p = await params;
  return proxyToBackend(buildBackendPath(p, req.nextUrl.search));
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const p = await params;
  const ct = req.headers.get("content-type") || "application/json";
  const authorName = await getAuthorName();
  return proxyToBackend(buildBackendPath(p, req.nextUrl.search), {
    method: "POST",
    headers: { "content-type": ct },
    body: req.body,
    // @ts-expect-error duplex needed for streaming body
    duplex: "half",
  }, { authorName });
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const p = await params;
  return proxyToBackend(buildBackendPath(p, req.nextUrl.search), {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: req.body,
    // @ts-expect-error duplex needed for streaming body
    duplex: "half",
  });
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const p = await params;
  return proxyToBackend(buildBackendPath(p, req.nextUrl.search), {
    method: "DELETE",
  });
}
