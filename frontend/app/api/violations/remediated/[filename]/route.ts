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

    // Determine if this is audio or media based on filename
    const isAudio = filename.includes("audio") || 
                    [".wav", ".mp3", ".m4a", ".ogg", ".aac", ".flac"].some(ext => filename.endsWith(ext));
    
    const backendEndpoint = isAudio 
      ? `/violations/audio/remediated/${filename}`
      : `/violations/media/remediated/${filename}`;

    const res = await fetch(
      `${BACKEND_URL}${backendEndpoint}`,
      { method: "GET" }
    );

    if (!res.ok) {
      return NextResponse.json(
        { success: false, message: `Failed to fetch remediated file: ${res.statusText}` },
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
      { success: false, message: err?.message || "Unexpected error while downloading remediated file" },
      { status: 500 }
    );
  }
}
