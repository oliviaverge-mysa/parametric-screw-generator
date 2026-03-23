import { proxyToBackend } from "@/lib/backend";
import { NextRequest } from "next/server";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const p = await params;
  const backendPath = `/downloads/${p.path.join("/")}`;
  const search = req.nextUrl.search;
  return proxyToBackend(search ? `${backendPath}${search}` : backendPath);
}
