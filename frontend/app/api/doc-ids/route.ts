import { NextRequest, NextResponse } from "next/server";

/**
 * GET /api/doc-ids
 * 
 * Proxy endpoint that fetches available document IDs from backend PageIndex service.
 * Returns map of available platforms and regions with their indexed guidelines.
 */
export async function GET(request: NextRequest) {
  try {
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
    const docIdsUrl = `${backendUrl}/doc_ids/`;

    const response = await fetch(docIdsUrl, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      console.error(`Backend /doc_ids/ returned ${response.status}`);
      return NextResponse.json(
        { error: "Failed to fetch available document IDs from backend" },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error("Error fetching doc-ids:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
