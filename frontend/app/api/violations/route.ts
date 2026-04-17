import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

interface ViolationsRequestBody {
  description: string;
  platforms?: string[];
  countries?: string[];
}

interface DocIdCountryItem {
  filename: string;
  doc_id: string;
  ready: boolean;
}

interface DocIdMediaItem {
  platform: string | null;
  filename: string;
  doc_id: string;
}

interface DocIdsResponse {
  country: DocIdCountryItem[];
  media: DocIdMediaItem[];
}

interface ViolationDocDescriptor {
  doc_id: string;
  label?: string | null;
}

interface ViolationDocResult {
  doc_id: string;
  label?: string | null;
  answer: string;
  sources: any[];
  reasoning: string;
  violations?: any[];
}

interface ViolationsBackendResponse {
  description: string;
  results: ViolationDocResult[];
}

function normaliseCountryName(name: string): string {
  return name.trim().toLowerCase().replace(/\s+/g, "_");
}

function buildLabelFromPlatform(platformId: string): string {
  if (!platformId) return "Media Guidelines";
  const id = platformId.toLowerCase();
  if (id === "youtube") return "YouTube Guidelines";
  if (id === "instagram") return "Instagram Guidelines";
  if (id === "twitter") return "Twitter / X Guidelines";
  return `${platformId} Guidelines`;
}

function buildLabelFromCountry(name: string): string {
  return `${name} Country Guidelines`;
}

export async function POST(req: Request) {
  const contentType = req.headers.get("content-type") || "";

  // Media mode (image/video) uses multipart/form-data and async backend jobs.
  if (contentType.includes("multipart/form-data")) {
    try {
      const formData = await req.formData();

      const file = formData.get("file");
      const mediaType = String(formData.get("media_type") || "");
      const description = String(formData.get("description") || "");

      const platformsRaw = formData.get("platforms");
      const countriesRaw = formData.get("countries");
      const includeAudioRaw = formData.get("include_audio");

      if (!(file instanceof File)) {
        return NextResponse.json(
          { success: false, message: "Media file is required" },
          { status: 400 }
        );
      }

      if (mediaType !== "image" && mediaType !== "video") {
        return NextResponse.json(
          { success: false, message: "media_type must be 'image' or 'video'" },
          { status: 400 }
        );
      }

      const outgoing = new FormData();
      outgoing.append("file", file);
      outgoing.append("media_type", mediaType);
      outgoing.append("description", description);
      outgoing.append("platforms", String(platformsRaw || "[]"));
      outgoing.append("countries", String(countriesRaw || "[]"));
      outgoing.append("include_audio", String(includeAudioRaw ?? "true"));
      outgoing.append("top_n_for_llm", "3");

      const mediaJobRes = await fetch(`${BACKEND_URL}/violations/media/jobs`, {
        method: "POST",
        body: outgoing,
      });

      const payload = await mediaJobRes.json();

      if (!mediaJobRes.ok) {
        return NextResponse.json(
          {
            success: false,
            message: payload?.detail || payload?.message || "Failed to create media analysis job",
          },
          { status: mediaJobRes.status }
        );
      }

      return NextResponse.json(payload, { status: 202 });
    } catch (err: any) {
      return NextResponse.json(
        {
          success: false,
          message: err?.message || "Unexpected error while creating media analysis job",
        },
        { status: 500 }
      );
    }
  }

  let body: ViolationsRequestBody;

  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { success: false, message: "Invalid JSON body" },
      { status: 400 }
    );
  }

  const description = (body.description || "").trim();
  const platforms = body.platforms || [];
  const countries = body.countries || [];

  if (!description) {
    return NextResponse.json(
      { success: false, message: "Description text is required" },
      { status: 400 }
    );
  }

  if (!BACKEND_URL) {
    return NextResponse.json(
      { success: false, message: "Backend URL is not configured" },
      { status: 500 }
    );
  }

  try {
    // 1) Fetch available doc_ids from backend (country + media)
    const docIdsRes = await fetch(`${BACKEND_URL}/doc_ids/`);

    if (!docIdsRes.ok) {
      const text = await docIdsRes.text();
      return NextResponse.json(
        {
          success: false,
          message: `Failed to fetch guideline documents (${docIdsRes.status}): ${text}`,
        },
        { status: 502 }
      );
    }

    const docIdsJson = (await docIdsRes.json()) as DocIdsResponse;

    const docs: ViolationDocDescriptor[] = [];

    // 2) Map selected platforms to media doc_ids
    if (platforms.length > 0 && Array.isArray(docIdsJson.media)) {
      const mediaByPlatform: Record<string, DocIdMediaItem[]> = {};

      for (const item of docIdsJson.media) {
        const key = (item.platform || "").toLowerCase();
        if (!key) continue;
        if (!mediaByPlatform[key]) mediaByPlatform[key] = [];
        mediaByPlatform[key].push(item);
      }

      for (const platformId of platforms) {
        const key = platformId.toLowerCase();
        const items = mediaByPlatform[key];
        if (!items || items.length === 0) continue;

        // For now, just take the first doc for each platform
        const chosen = items[0];
        docs.push({
          doc_id: chosen.doc_id,
          label: buildLabelFromPlatform(platformId),
        });
      }
    }

    // 3) Map selected countries to country doc_ids
    if (countries.length > 0 && Array.isArray(docIdsJson.country)) {
      const countryByKey: Record<string, DocIdCountryItem[]> = {};

      for (const item of docIdsJson.country) {
        const base = item.filename.replace(/\.pdf$/i, "");
        const key = normaliseCountryName(base);
        if (!countryByKey[key]) countryByKey[key] = [];
        countryByKey[key].push(item);
      }

      for (const countryName of countries) {
        const key = normaliseCountryName(countryName);
        const items = countryByKey[key];
        if (!items || items.length === 0) continue;

        const chosen = items[0];
        docs.push({
          doc_id: chosen.doc_id,
          label: buildLabelFromCountry(countryName),
        });
      }
    }

    if (docs.length === 0) {
      return NextResponse.json(
        {
          success: false,
          message:
            "No matching guideline documents were found for the selected platforms/regions.",
        },
        { status: 400 }
      );
    }

    // 4) Call backend violations/query
    const violationsRes = await fetch(`${BACKEND_URL}/violations/query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        description,
        docs,
        top_n_for_llm: 3,
      }),
    });

    if (!violationsRes.ok) {
      const text = await violationsRes.text();
      return NextResponse.json(
        {
          success: false,
          message: `Violation analysis failed (${violationsRes.status}): ${text}`,
        },
        { status: 502 }
      );
    }

    const violationsJson = (await violationsRes.json()) as ViolationsBackendResponse;

    return NextResponse.json({
      success: true,
      description: violationsJson.description,
      results: violationsJson.results,
    });
  } catch (err: any) {
    return NextResponse.json(
      {
        success: false,
        message: err?.message || "Unexpected error while contacting backend",
      },
      { status: 500 }
    );
  }
}


export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const jobId = searchParams.get("jobId");

  if (!jobId) {
    return NextResponse.json(
      { success: false, message: "jobId query parameter is required" },
      { status: 400 }
    );
  }

  try {
    const res = await fetch(`${BACKEND_URL}/violations/media/jobs/${jobId}`, {
      method: "GET",
    });

    const payload = await res.json();

    if (!res.ok) {
      return NextResponse.json(
        {
          success: false,
          message: payload?.detail || payload?.message || "Failed to fetch job status",
        },
        { status: res.status }
      );
    }

    return NextResponse.json(payload);
  } catch (err: any) {
    return NextResponse.json(
      {
        success: false,
        message: err?.message || "Unexpected error while fetching media job",
      },
      { status: 500 }
    );
  }
}
