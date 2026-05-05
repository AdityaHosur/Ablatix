import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ filename: string }> }
) {
  try {
    const { filename } = await params;

    if (!filename) {
      return NextResponse.json(
        { success: false, message: "Filename is required" },
        { status: 400 }
      );
    }

    const res = await fetch(
      `${BACKEND_URL}/violations/media/remediated/${filename}`,
      { method: "GET" }
    );

    if (!res.ok) {
      return NextResponse.json(
        { success: false, message: `Failed to fetch remediated media: ${res.statusText}` },
        { status: res.status }
      );
    }

    // Get the blob and pass it through
    const blob = await res.blob();
    const contentType = res.headers.get("content-type") || "application/octet-stream";

    return new NextResponse(blob, {
      status: 200,
      headers: {
        "Content-Type": contentType,
        "Content-Disposition": `attachment; filename="${filename}"`,
      },
    });
  } catch (err: any) {
    return NextResponse.json(
      { success: false, message: err?.message || "Unexpected error while downloading remediated media" },
      { status: 500 }
    );
  }
}
