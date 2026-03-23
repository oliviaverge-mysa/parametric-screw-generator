import { proxyToBackend } from "@/lib/backend";
import { NextRequest } from "next/server";

export async function GET() {
  return proxyToBackend("/api/chats");
}

export async function POST(req: NextRequest) {
  return proxyToBackend("/api/chats", {
    method: "POST",
    headers: { "content-type": req.headers.get("content-type") || "application/json" },
    body: req.body,
    // @ts-expect-error duplex needed for streaming body
    duplex: "half",
  });
}

export async function DELETE() {
  return proxyToBackend("/api/chats", { method: "DELETE" });
}
