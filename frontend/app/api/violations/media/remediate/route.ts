import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const res = await fetch(`${BACKEND_URL}/violations/media/remediate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const payload = await res.json().catch(() => null);

    if (!res.ok) {
      return NextResponse.json(
        { success: false, detail: payload?.detail || payload || "Remediation failed" },
        { status: res.status }
      );
    }

    return NextResponse.json(payload, { status: res.status });
  } catch (err: any) {
    return NextResponse.json(
      { success: false, message: err?.message || "Unexpected error while proxying remediation request" },
      { status: 500 }
    );
  }
}
