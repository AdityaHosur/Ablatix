import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

export async function POST(req: Request) {
  const contentType = req.headers.get("content-type") || "";

  // Audio mode uses multipart/form-data
  if (contentType.includes("multipart/form-data")) {
    try {
      const formData = await req.formData();

      const file = formData.get("file");
      const description = String(formData.get("description") || "");
      const platformsRaw = formData.get("platforms");
      const countriesRaw = formData.get("countries");
      const topNRaw = formData.get("top_n_for_llm");

      if (!(file instanceof File)) {
        return NextResponse.json(
          { success: false, message: "Audio file is required" },
          { status: 400 }
        );
      }

      const outgoing = new FormData();
      outgoing.append("file", file);
      outgoing.append("description", description);
      outgoing.append("platforms", String(platformsRaw || "[]"));
      outgoing.append("countries", String(countriesRaw || "[]"));
      outgoing.append("top_n_for_llm", String(topNRaw || "3"));

      const backendRes = await fetch(`${BACKEND_URL}/violations/audio/jobs`, {
        method: "POST",
        body: outgoing,
      });

      const data = await backendRes.json();

      if (!backendRes.ok) {
        return NextResponse.json(
          { success: false, message: data?.detail || "Backend error" },
          { status: backendRes.status }
        );
      }

      return NextResponse.json(data, { status: 200 });
    } catch (error: any) {
      console.error("Audio job creation error:", error);
      return NextResponse.json(
        { success: false, message: error.message || "Internal error" },
        { status: 500 }
      );
    }
  }

  return NextResponse.json(
    { success: false, message: "Invalid content type" },
    { status: 400 }
  );
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const jobId = searchParams.get("jobId");

  if (!jobId) {
    return NextResponse.json(
      { success: false, message: "jobId is required" },
      { status: 400 }
    );
  }

  try {
    const backendRes = await fetch(`${BACKEND_URL}/violations/media/jobs/${jobId}`);
    const data = await backendRes.json();

    if (!backendRes.ok) {
      return NextResponse.json(
        { success: false, message: data?.detail || "Backend error" },
        { status: backendRes.status }
      );
    }

    return NextResponse.json(data, { status: 200 });
  } catch (error: any) {
    console.error("Audio job fetch error:", error);
    return NextResponse.json(
      { success: false, message: error.message || "Internal error" },
      { status: 500 }
    );
  }
}
