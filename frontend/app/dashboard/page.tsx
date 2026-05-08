"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Upload,
  Youtube,
  Instagram,
  Twitter,
  CheckCircle2,
  ShieldCheck,
  Zap,
  X,
  BarChart3,
  LogOut,
  ChevronUp,
} from "lucide-react";

const PLATFORMS = [
  { id: "youtube", name: "YouTube", icon: <Youtube className="w-5 h-5 text-red-500" /> },
  { id: "instagram", name: "Instagram", icon: <Instagram className="w-5 h-5 text-pink-500" /> },
  { id: "twitter", name: "X / Twitter", icon: <Twitter className="w-5 h-5 text-slate-900" /> },
];

const COUNTRIES = ["India", "USA", "UAE", "UK", "Singapore"];

type PlatformOption = {
  id: string;
  name: string;
  icon: React.ReactNode;
};

type CountryOption = string;

function prettifyLabel(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function platformIcon(platformId: string) {
  const key = platformId.toLowerCase();
  if (key === "youtube") return <Youtube className="w-5 h-5 text-red-500" />;
  if (key === "instagram") return <Instagram className="w-5 h-5 text-pink-500" />;
  if (key === "twitter" || key === "x") return <Twitter className="w-5 h-5 text-slate-900" />;
  return <ShieldCheck className="w-5 h-5 text-slate-400" />;
}

function platformLabel(platformId: string) {
  const key = platformId.toLowerCase();
  if (key === "youtube") return "YouTube";
  if (key === "instagram") return "Instagram";
  if (key === "twitter" || key === "x") return "X / Twitter";
  return prettifyLabel(platformId);
}

function inferPlatformId(item: { platform?: string | null; filename: string }) {
  if (item.platform) return item.platform.toLowerCase();
  const base = item.filename.replace(/\.pdf$/i, "");
  if (base.includes("_guidelines_")) {
    return base.split("_guidelines_", 1)[0].toLowerCase();
  }
  return base.toLowerCase();
}

function inferCountryName(filename: string) {
  const base = filename.replace(/\.pdf$/i, "").trim();
  const compact = base.replace(/[_\s-]+/g, "");

  if (compact.length > 0 && compact.length <= 4 && /^[a-zA-Z]+$/.test(compact)) {
    return compact.toUpperCase();
  }

  return prettifyLabel(base);
}

function summarizeSources(sources: any[]) {
  if (!Array.isArray(sources) || sources.length === 0) return [];

  return sources
    .map((source: any) => {
      const title = source?.title || source?.node_id || "Guideline reference";
      const pageIndex = source?.page_index ? `p.${source.page_index}` : null;
      return [title, pageIndex].filter(Boolean).join(" ");
    })
    .filter(Boolean);
}

function renderViolationBoxes(violations: any[]) {
  if (!Array.isArray(violations) || violations.length === 0) return null;

  return violations.flatMap((violation: any, violationIndex: number) => {
    const regions = Array.isArray(violation?.regions) ? violation.regions : [];
    return regions.map((region: any, regionIndex: number) => ({
      key: `${violationIndex}-${regionIndex}`,
      region,
    }));
  });
}

function normalizeRemediatedText(text: string) {
  return text.replace(/\*{5,}/g, "******");
}

export default function ComplianceDashboard() {
  const [mounted, setMounted] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([]);
  const [selectedCountries, setSelectedCountries] = useState<string[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [mode, setMode] = useState<"image" | "video" | "audio" | "text">("image");
  const [textInput, setTextInput] = useState("");
  const [showResults, setShowResults] = useState(false);
  const [isRemediating, setIsRemediating] = useState(false);
  const [isRemediated, setIsRemediated] = useState(false);
  const [showRemediatedText, setShowRemediatedText] = useState(false);
  const [progress, setProgress] = useState(0);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisResults, setAnalysisResults] = useState<any[] | null>(null);
  const [mediaAnalysisResult, setMediaAnalysisResult] = useState<any | null>(null);
  const [mediaJobId, setMediaJobId] = useState<string | null>(null);
  const [mediaJobStage, setMediaJobStage] = useState<string>("");
  const [mediaJobProgress, setMediaJobProgress] = useState<number>(0);
  const [lastMediaJobId, setLastMediaJobId] = useState<string | null>(null);
  const [remediationData, setRemediationData] = useState<any | null>(null);
  const [remediationStats, setRemediationStats] = useState<any | null>(null);
  const [availableDocIds, setAvailableDocIds] = useState<any>({});
  const [isLoadingDocIds, setIsLoadingDocIds] = useState(true);
  const [user, setUser] = useState<any>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  useEffect(() => {
    const u = localStorage.getItem("user");
    if (u) setUser(JSON.parse(u));
  }, []);

  useEffect(() => {
    const fetchDocIds = async () => {
      try {
        const res = await fetch("/api/doc-ids");
        if (res.ok) {
          const data = await res.json();
          setAvailableDocIds(data);
        }
      } catch (error) {
        console.error("Failed to fetch available doc-ids:", error);
      } finally {
        setIsLoadingDocIds(false);
      }
    };

    fetchDocIds();
  }, []);

  useEffect(() => {
    if (!mediaJobId) return;

    let alive = true;
    let timer: any;

    const poll = async () => {
      try {
        const res = await fetch(`/api/violations?jobId=${mediaJobId}`);
        const data = await res.json();

        if (!alive) return;

        if (!res.ok) {
          setAnalysisError(data?.message || "Failed to fetch media analysis status.");
          setAnalysisLoading(false);
          setMediaJobId(null);
          return;
        }

        setMediaJobStage(data.stage || data.status || "processing");
        setMediaJobProgress(data.progress || 0);

        if (data.status === "completed") {
          setAnalysisResults(data?.result?.results || []);
          setMediaAnalysisResult(data?.result || null);
          if (data?.result?.remediation) {
            setRemediationData(data.result.remediation);
            setRemediationStats(data.result.remediation.stats);
          }
          setAnalysisLoading(false);
          setMediaJobId(null);
          return;
        }

        if (data.status === "failed") {
          const firstError = Array.isArray(data.errors) && data.errors.length > 0 ? data.errors[0]?.message : null;
          setAnalysisError(firstError || "Media analysis failed.");
          setAnalysisLoading(false);
          setMediaJobId(null);
          return;
        }

        timer = setTimeout(poll, 2000);
      } catch {
        if (!alive) return;
        setAnalysisError("Error while polling media analysis status.");
        setAnalysisLoading(false);
        setMediaJobId(null);
      }
    };

    poll();

    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [mediaJobId]);

  const toggle = (list: string[], setList: React.Dispatch<React.SetStateAction<string[]>>, id: string) => {
    setList(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  };

  const getInitials = (name: string) =>
    name
      ?.split(" ")
      .map((word) => word[0])
      .join("")
      .toUpperCase();

  const platformOptions: PlatformOption[] = (() => {
    const media = Array.isArray(availableDocIds?.media) ? availableDocIds.media : [];
    if (isLoadingDocIds || media.length === 0) return PLATFORMS;

    const seen = new Set<string>();
    const options: PlatformOption[] = [];

    for (const item of media) {
      const platformId = inferPlatformId(item);
      if (!platformId || seen.has(platformId)) continue;
      seen.add(platformId);
      options.push({ id: platformId, name: platformLabel(platformId), icon: platformIcon(platformId) });
    }

    return options.length > 0 ? options : PLATFORMS;
  })();

  const countryOptions: CountryOption[] = (() => {
    const countries = Array.isArray(availableDocIds?.country) ? availableDocIds.country : [];
    if (isLoadingDocIds || countries.length === 0) return COUNTRIES;

    const options = countries.map((item: any) => inferCountryName(item.filename));
    return options.length > 0 ? options : COUNTRIES;
  })();

  const displayedResults = Array.isArray(analysisResults) ? analysisResults : [];
  const totalViolationItems = displayedResults.reduce((count, result: any) => count + (Array.isArray(result?.violations) ? result.violations.length : 0), 0);

  const getMediaFrameAnalyses = () => (Array.isArray(mediaAnalysisResult?.frame_analyses) ? mediaAnalysisResult.frame_analyses : []);

  const handleFile = (uploadedFile: File) => {
    if (
      (mode === "image" && !uploadedFile.type.startsWith("image/")) ||
      (mode === "video" && !uploadedFile.type.startsWith("video/")) ||
      (mode === "audio" && !uploadedFile.type.startsWith("audio/"))
    ) {
      alert("Invalid file type selected");
      return;
    }

    setFile(uploadedFile);
    const url = URL.createObjectURL(uploadedFile);
    setPreviewUrl(url);

    setIsRemediated(false);
    setShowRemediatedText(false);
    setShowResults(false);
    setProgress(0);
    setMediaAnalysisResult(null);
    setRemediationData(null);
    setRemediationStats(null);
    setLastMediaJobId(null);
  };

  const handleDownload = async () => {
    if (mode === "text") {
      const downloadText = isRemediated && remediationData ? remediationData.remediated_text || textInput : textInput;
      const blob = new Blob([downloadText], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "remediated.txt";
      a.click();
      URL.revokeObjectURL(url);
      return;
    }

    if (!remediationData) {
      alert("Remediated file not available. Please run remediation first.");
      return;
    }

    const remediatedPath = mode === "image" ? remediationData.image_path : mode === "audio" ? remediationData.audio_path : remediationData.video_path;
    if (!remediatedPath) {
      alert("Remediated file not available. Please run remediation first.");
      return;
    }

    try {
      const filename = remediatedPath.split("/").pop() || `remediated.${mode === "video" ? "mp4" : "png"}`;
      const downloadUrl = `/api/violations/remediated/${filename}`;
      const response = await fetch(downloadUrl);
      if (!response.ok) throw new Error(`Failed to download remediated ${mode}: ${response.statusText}`);

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Download error:", err);
      alert(`Failed to download remediated ${mode}. Please try again.`);
    }
  };

  const runTextAnalysis = async () => {
    if (analysisLoading) return;
    if (!textInput.trim()) return;

    setShowResults(true);
    setAnalysisLoading(true);
    setAnalysisError(null);
    setAnalysisResults(null);
    setMediaAnalysisResult(null);
    setIsRemediated(false);
    setShowRemediatedText(false);
    setRemediationData(null);
    setRemediationStats(null);

    try {
      const res = await fetch("/api/violations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          description: textInput,
          platforms: selectedPlatforms,
          countries: selectedCountries,
        }),
      });

      const data = await res.json();

      if (!res.ok || !data.success) {
        setAnalysisError(data?.message || "Analysis failed. Please try again or adjust your selections.");
        setAnalysisResults(null);
        return;
      }

      setAnalysisResults(data.results || []);
    } catch (err: any) {
      setAnalysisError(err?.message || "Unable to contact analysis service. Please try again.");
      setAnalysisResults(null);
    } finally {
      setAnalysisLoading(false);
    }
  };

  const runMediaAnalysis = async () => {
    if (analysisLoading) return;
    if (!file) return;

    setShowResults(true);
    setAnalysisLoading(true);
    setAnalysisError(null);
    setAnalysisResults(null);
    setMediaAnalysisResult(null);
    setMediaJobId(null);
    setLastMediaJobId(null);
    setMediaJobStage("queued");
    setMediaJobProgress(0);
    setIsRemediated(false);
    setShowRemediatedText(false);
    setRemediationData(null);
    setRemediationStats(null);

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("media_type", mode);
      formData.append("description", textInput || "");
      formData.append("platforms", JSON.stringify(selectedPlatforms));
      formData.append("countries", JSON.stringify(selectedCountries));
      formData.append("include_audio", "true");

      const res = await fetch("/api/violations", { method: "POST", body: formData });
      const data = await res.json();

      if (!res.ok || !data.job_id) {
        setAnalysisError(data?.message || data?.detail || "Failed to start media analysis job.");
        setAnalysisLoading(false);
        return;
      }

      setMediaJobId(data.job_id);
      setLastMediaJobId(data.job_id);
    } catch (err: any) {
      setAnalysisError(err?.message || "Unable to start media analysis. Please try again.");
      setAnalysisLoading(false);
    }
  };

  const runAudioAnalysis = async () => {
    if (analysisLoading) return;
    if (!file) return;

    setShowResults(true);
    setAnalysisLoading(true);
    setAnalysisError(null);
    setAnalysisResults(null);
    setMediaAnalysisResult(null);
    setMediaJobId(null);
    setLastMediaJobId(null);
    setMediaJobStage("queued");
    setMediaJobProgress(0);

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("description", textInput || "");
      formData.append("platforms", JSON.stringify(selectedPlatforms));
      formData.append("countries", JSON.stringify(selectedCountries));

      const res = await fetch("/api/violations/audio", { method: "POST", body: formData });
      const data = await res.json();

      if (!res.ok || !data.job_id) {
        setAnalysisError(data?.message || data?.detail || "Failed to start audio analysis job.");
        setAnalysisLoading(false);
        return;
      }

      setMediaJobId(data.job_id);
      setLastMediaJobId(data.job_id);
    } catch (err: any) {
      setAnalysisError(err?.message || "Unable to start audio analysis. Please try again.");
      setAnalysisLoading(false);
    }
  };

  const handleRemediate = async () => {
    if (mode !== "text") {
      const jobToRemediate = mediaJobId || lastMediaJobId;
      if (!jobToRemediate) {
        const persistedPath = mediaAnalysisResult?.storage_path || mediaAnalysisResult?.result?.storage_path || remediationData?.storage_path || null;
        if (!persistedPath) {
          alert("No media job available to remediate.");
          return;
        }
      }
    }

    setIsRemediating(true);
    try {
      let res: Response;
      if (mode === "text") {
        res = await fetch("/api/violations/text/remediate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text_input: textInput, mode: "mask" }),
        });
      } else if (mode === "audio") {
        const audioPayload: any = {};
        const jobToRemediate = mediaJobId || lastMediaJobId;
        if (jobToRemediate) audioPayload.job_id = jobToRemediate;
        else audioPayload.storage_path = mediaAnalysisResult?.storage_path || mediaAnalysisResult?.result?.storage_path || null;

        res = await fetch("/api/violations/audio/remediate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(audioPayload),
        });
      } else {
        const mediaPayload: any = {};
        const jobToRemediate = mediaJobId || lastMediaJobId;
        if (jobToRemediate) mediaPayload.job_id = jobToRemediate;
        else mediaPayload.storage_path = mediaAnalysisResult?.storage_path || mediaAnalysisResult?.result?.storage_path || null;

        res = await fetch("/api/violations/media/remediate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(mediaPayload),
        });
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText || "Remediation failed");
      }

      const data = await res.json();
      if (data?.success && data.remediation) {
        if (mode === "text" && typeof data.remediation.remediated_text === "string") {
          data.remediation.remediated_text = normalizeRemediatedText(data.remediation.remediated_text);
        }
        setRemediationData(data.remediation);
        setRemediationStats(data.remediation.stats || null);
        setIsRemediated(true);
      } else {
        throw new Error("Remediation did not complete successfully");
      }
    } catch (err: any) {
      console.error("Remediation error:", err);
      alert(`Remediation failed: ${err?.message || err}`);
    } finally {
      setIsRemediating(false);
    }
  };

  const hasViolations = (() => {
    if (mode === "text") {
      return Boolean(
        analysisResults &&
          Array.isArray(analysisResults) &&
          analysisResults.some((r: any) => Array.isArray(r.violations) && r.violations.length > 0)
      );
    }

    if (!mediaAnalysisResult) return false;

    if (Array.isArray(mediaAnalysisResult.frame_analyses) && mediaAnalysisResult.frame_analyses.some((f: any) => Array.isArray(f.violations) && f.violations.length > 0)) {
      return true;
    }

    if (Array.isArray(mediaAnalysisResult.results) && mediaAnalysisResult.results.some((r: any) => Array.isArray(r.violations) && r.violations.length > 0)) {
      return true;
    }

    return false;
  })();

  return (
    <div className="min-h-screen bg-slate-50 flex font-[family-name:var(--font-geist-sans)] text-slate-900">
      <aside className="w-72 bg-white border-r border-slate-200 p-6 flex flex-col fixed h-full">
        <div className="flex items-center gap-2 font-bold text-xl text-indigo-600 mb-8">
          <ShieldCheck className="w-6 h-6" /> Ablatix
        </div>

        <div className="space-y-8 flex-1 overflow-y-auto pb-4">
          <div>
            <label className="text-[10px] font-bold text-slate-400 uppercase tracking-widest block mb-4">Platforms</label>
            <div className="space-y-2">
              {platformOptions.map((p) => (
                <button key={p.id} onClick={() => toggle(selectedPlatforms, setSelectedPlatforms, p.id)} className={`w-full flex items-center justify-between p-3 rounded-xl border-2 transition-all ${selectedPlatforms.includes(p.id) ? "border-indigo-600 bg-indigo-50" : "border-slate-50 bg-white hover:border-slate-200"}`}>
                  <div className="flex items-center gap-2">{p.icon} <span className="text-sm font-semibold text-slate-700">{p.name}</span></div>
                  {selectedPlatforms.includes(p.id) && <CheckCircle2 className="w-4 h-4 text-indigo-600 fill-indigo-50" />}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-[10px] font-bold text-slate-400 uppercase tracking-widest block mb-4">Target Regions</label>
            <div className="flex flex-wrap gap-2">
              {countryOptions.map((c) => (
                <button key={c} onClick={() => toggle(selectedCountries, setSelectedCountries, c)} className={`px-3 py-1.5 rounded-full border text-[11px] font-bold transition-all ${selectedCountries.includes(c) ? "bg-slate-900 text-white" : "bg-white text-slate-500 hover:border-slate-400"}`}>
                  {c}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="relative pt-6 border-t border-slate-100">
          <button onClick={() => setIsProfileOpen(!isProfileOpen)} className="w-full flex items-center gap-3 p-3 rounded-2xl hover:bg-slate-50">
            <div className="w-10 h-10 rounded-full bg-indigo-600 flex items-center justify-center text-white font-bold">{!mounted ? "DR" : user ? getInitials(user.name) : "DR"}</div>
            <div className="text-left flex-1"><p className="text-sm font-bold text-slate-900">{!mounted ? "User" : user ? user.name : "User"}</p></div>
            <ChevronUp />
          </button>
          {isProfileOpen && (
            <div className="absolute bottom-20 left-0 w-full bg-white rounded-3xl shadow-2xl border p-2">
              <Link href="/analytics" className="flex items-center gap-3 px-4 py-3 text-sm font-bold text-slate-600 hover:bg-indigo-50"><BarChart3 /> View Analytics</Link>
              <button onClick={() => { window.location.href = "/"; }} className="flex items-center gap-3 px-4 py-3 text-sm font-bold text-red-500 hover:bg-red-50"><LogOut /> Sign Out</button>
            </div>
          )}
        </div>
      </aside>

      <main className="flex-1 ml-72 p-6 lg:p-10 min-h-screen flex flex-col gap-6">
        <header className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Compliance Studio</h2>
            {mounted && user && <h3 className="text-sm font-semibold text-indigo-600 mt-1">Welcome to {user.name}&apos;s Workspace</h3>}
          </div>

          <button onClick={async () => {
            setIsRemediated(false);
            setIsRemediating(false);
            setProgress(0);
            if (mode === "text") {
              await runTextAnalysis();
            } else if (mode === "audio") {
              await runAudioAnalysis();
            } else {
              await runMediaAnalysis();
            }
          }} disabled={mode === "text" ? !textInput.trim() || analysisLoading : !file || analysisLoading} className="bg-indigo-600 disabled:opacity-30 text-white px-6 py-3 rounded-xl font-bold flex items-center gap-2 self-start"><Zap /> {analysisLoading ? "Running..." : "Run Analysis"}</button>
        </header>

        <div className="flex gap-3 flex-wrap">
          {(["image", "video", "audio", "text"] as const).map((m) => (
            <button key={m} onClick={() => {
              setMode(m);
              setFile(null);
              setTextInput("");
              setIsRemediated(false);
              setShowRemediatedText(false);
              setShowResults(false);
              setProgress(0);
              setMediaAnalysisResult(null);
              setRemediationData(null);
              setRemediationStats(null);
              setLastMediaJobId(null);
            }} className={`px-4 py-2 rounded-xl font-bold capitalize border transition-all ${mode === m ? "border-indigo-600 bg-indigo-50 text-indigo-600" : "border-slate-200 text-slate-500 hover:border-slate-400"}`}>{m}</button>
          ))}
        </div>

        <section className="rounded-[2rem] border border-slate-200 bg-white shadow-sm p-5 relative transition-all hover:border-indigo-300 max-w-3xl">
          {isRemediating && <div className="absolute inset-0 pointer-events-none flex items-center justify-center rounded-[2rem] overflow-hidden"><div className="absolute inset-0 bg-indigo-500/10" /><div className="absolute w-full h-24 bg-gradient-to-b from-transparent via-indigo-400/40 to-transparent animate-scan" /><div className="relative z-10 bg-white/80 backdrop-blur px-6 py-3 rounded-xl shadow text-indigo-600 font-bold">{progress}%</div></div>}

          {mode === "text" ? (
            <textarea value={textInput} onChange={(e) => {
              const value = e.target.value;
              setTextInput(value);
              if (value.trim() === "") {
                setShowResults(false);
                setIsRemediated(false);
                setIsRemediating(false);
                setProgress(0);
                setRemediationData(null);
                setRemediationStats(null);
              }
            }} placeholder="Enter the text..." className="w-full h-48 outline-none text-slate-700 resize-none" />
          ) : (
            <div onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }} onDragLeave={() => setIsDragging(false)} onDrop={(e) => { e.preventDefault(); setIsDragging(false); if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]); }} className={`rounded-[1.75rem] border-2 border-dashed transition-all flex items-center justify-center relative overflow-hidden bg-slate-50 min-h-[240px] ${isDragging ? "border-indigo-500 bg-indigo-50" : "border-slate-200 hover:border-indigo-300"}`}>
              <input type="file" accept={mode === "image" ? "image/*" : mode === "audio" ? "audio/*" : "video/*"} ref={fileInputRef} className="hidden" onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])} />

              {!file ? (
                <div className="text-center cursor-pointer px-4" onClick={() => fileInputRef.current?.click()}>
                  <div className="w-16 h-16 bg-indigo-50 rounded-2xl flex items-center justify-center mx-auto mb-4"><Upload className="text-indigo-600" /></div>
                  <p className="font-bold text-slate-700">Drag &amp; Drop {mode === "image" ? "Image" : mode === "audio" ? "Audio" : "Video"}</p>
                  <p className="text-slate-400 text-sm mt-1 uppercase tracking-widest font-bold">Click to browse</p>
                </div>
              ) : (
                <div className="w-full h-full p-4 flex flex-col items-center">
                  <button onClick={() => {
                    setFile(null);
                    setShowResults(false);
                    setIsRemediated(false);
                    setIsRemediating(false);
                    setProgress(0);
                    setMediaAnalysisResult(null);
                    setRemediationData(null);
                    setRemediationStats(null);
                  }} className="absolute top-6 right-6 z-20 p-2 bg-white/80 backdrop-blur rounded-full shadow-md hover:text-red-500"><X /></button>

                  <div className="w-full min-h-[180px] flex items-center justify-center rounded-2xl overflow-hidden bg-slate-900 shadow-inner">
                    {mode === "video" ? (
                      <video src={previewUrl!} controls className="max-w-full max-h-full" />
                    ) : (
                      <div className="relative inline-block max-w-full max-h-full">
                        <img src={previewUrl!} alt="Preview" className="block max-w-full max-h-full object-contain" />
                        {getMediaFrameAnalyses()[0]?.violations && renderViolationBoxes(getMediaFrameAnalyses()[0].violations)?.map(({ key, region }) => (
                          <div key={key} className="absolute border-2 border-emerald-500 bg-emerald-400/10 shadow-[0_0_0_1px_rgba(34,197,94,0.35)]" style={{ left: `${Math.max(0, Number(region?.x || 0)) * 100}%`, top: `${Math.max(0, Number(region?.y || 0)) * 100}%`, width: `${Math.max(0, Number(region?.width || 0)) * 100}%`, height: `${Math.max(0, Number(region?.height || 0)) * 100}%` }} />
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        {showResults && (
          <section className="w-full bg-white border border-slate-200 rounded-[2.5rem] shadow-sm p-6 flex flex-col min-w-0">
            <div className="flex flex-col gap-4 mb-6">
              <div className="rounded-[1.5rem] bg-slate-950 text-white p-5">
                <p className="text-[11px] uppercase tracking-[0.3em] text-slate-300 font-bold">Detected Violations</p>
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <div className="px-3 py-1.5 rounded-full bg-white/10 border border-white/10 text-sm font-semibold">{displayedResults.length} guideline{displayedResults.length === 1 ? "" : "s"} checked</div>
                  <div className="px-3 py-1.5 rounded-full bg-rose-500/15 border border-rose-400/30 text-sm font-semibold text-rose-100">{totalViolationItems} violation{totalViolationItems === 1 ? "" : "s"} identified</div>
                  <div className="text-sm text-slate-300">Guidelines are analyzed one by one so each result stays readable and token limits stay bounded.</div>
                </div>
              </div>
            </div>

            <div className="flex-1 space-y-4">
              {analysisLoading && mode === "text" && <div className="p-4 rounded-2xl bg-indigo-50 border border-indigo-200 text-sm text-indigo-700 font-medium">Running guideline checks one by one so each selection stays explainable and token-safe...</div>}
              {analysisLoading && mode !== "text" && <div className="p-4 rounded-2xl bg-indigo-50 border border-indigo-200 text-sm text-indigo-700 font-medium">Processing {mode} job: {mediaJobStage || "processing"} ({mediaJobProgress}%)</div>}
              {analysisError && <div className="p-4 rounded-2xl bg-red-50 border border-red-200 text-sm text-red-700 font-medium">{analysisError}</div>}

              {!analysisLoading && !analysisError && mode !== "text" && Array.isArray(mediaAnalysisResult?.frame_analyses) && mediaAnalysisResult.frame_analyses.length > 0 && (
                <div className="space-y-4">
                  <p className="text-[11px] text-slate-500 font-bold uppercase tracking-wide">Visual evidence</p>
                  {mediaAnalysisResult.frame_analyses.map((frame: any, frameIndex: number) => {
                    const frameViolations = Array.isArray(frame?.violations) ? frame.violations : [];
                    return (
                      <div key={`${frameIndex}-${frame?.timestamp ?? "frame"}`} className="rounded-2xl border border-emerald-200 bg-emerald-50/60 p-4 space-y-3">
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-bold text-emerald-700">Frame {frameIndex + 1}</p>
                          <p className="text-[11px] text-slate-500">{typeof frame?.timestamp === "number" ? `${frame.timestamp.toFixed(2)}s` : "timestamp unavailable"}</p>
                        </div>

                        {frame.frame_preview ? (
                          <div className="relative inline-block max-w-full overflow-hidden rounded-lg border border-emerald-200 bg-white">
                            <img src={frame.frame_preview} alt={`Analyzed frame ${frameIndex + 1}`} className="block max-w-full h-auto" />
                            {renderViolationBoxes(frameViolations)?.map(({ key, region }) => (
                              <div key={key} className="absolute border-2 border-emerald-500 bg-emerald-400/10" style={{ left: `${Math.max(0, Number(region?.x || 0)) * 100}%`, top: `${Math.max(0, Number(region?.y || 0)) * 100}%`, width: `${Math.max(0, Number(region?.width || 0)) * 100}%`, height: `${Math.max(0, Number(region?.height || 0)) * 100}%` }} />
                            ))}
                          </div>
                        ) : null}

                        {frame.description && <p className="text-sm text-slate-700 leading-6">{frame.description}</p>}
                      </div>
                    );
                  })}
                </div>
              )}

              {!analysisLoading && !analysisError && displayedResults.length > 0 ? (
                displayedResults.map((result, i) => {
                  const label = result.label || `Guideline ${i + 1}`;
                  const violations = Array.isArray(result.violations) ? result.violations : [];
                  const answer: string = result.answer || "";
                  const sources = summarizeSources(result.sources);

                  return (
                    <div key={result.doc_id || i} className="rounded-[2rem] border border-slate-200 bg-slate-50/60 p-5 space-y-4">
                      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                        <div>
                          <p className="text-[11px] text-red-600 font-bold uppercase tracking-[0.2em]">Guideline</p>
                          <h4 className="text-lg font-bold text-slate-950 mt-1">{label}</h4>
                        </div>
                        <div className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-bold ${violations.length > 0 ? "bg-rose-100 text-rose-700" : "bg-emerald-100 text-emerald-700"}`}>
                          {violations.length > 0 ? `${violations.length} violation${violations.length === 1 ? "" : "s"} found` : "No structured violation returned"}
                        </div>
                      </div>

                      <div className="rounded-2xl bg-white border border-slate-200 p-4">
                        <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Why it is violated</p>
                        <p className="mt-2 text-sm leading-6 text-slate-700 whitespace-pre-line">{answer || "The guideline response did not provide a structured summary, but the detected issue still needs review below."}</p>
                      </div>

                      {violations.length > 0 ? (
                        <div className="space-y-4">
                          {violations.map((violation: any, vIdx: number) => (
                            <div key={vIdx} className="p-5 rounded-2xl bg-white border border-red-200 shadow-sm space-y-4">
                              <div className="flex gap-3">
                                <span className="bg-red-600 text-white w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0">{vIdx + 1}</span>
                                <div className="flex-1 space-y-4">
                                  <div className="space-y-2">
                                    <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">What is violated</p>
                                    <div className="text-sm text-slate-900 font-semibold leading-6">{violation.ref || "Violation identified"}</div>
                                    {violation.explanation && <p className="text-sm leading-6 text-slate-700">{violation.explanation}</p>}
                                  </div>

                                  {violation.remediation && (
                                    <div className="rounded-2xl bg-amber-50 border border-amber-200 p-4">
                                      <p className="text-[11px] font-bold uppercase tracking-wide text-amber-800">What to do differently</p>
                                      <p className="mt-2 text-sm leading-6 text-amber-900">{violation.remediation}</p>
                                    </div>
                                  )}

                                  {sources.length > 0 && (
                                    <div className="rounded-2xl bg-slate-50 border border-slate-200 p-4">
                                      <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Guideline references</p>
                                      <ul className="mt-2 space-y-2">
                                        {sources.map((source: string, sourceIndex: number) => (
                                          <li key={sourceIndex} className="text-sm text-slate-700 flex gap-2">
                                            <span className="mt-1 h-1.5 w-1.5 rounded-full bg-slate-400 flex-shrink-0" />
                                            <span>{source}</span>
                                          </li>
                                        ))}
                                      </ul>
                                    </div>
                                  )}
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="p-5 rounded-2xl bg-white border border-slate-200 text-sm space-y-4 shadow-sm">
                          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">What the guideline says</p>
                          <p className="text-slate-800 leading-6 whitespace-pre-line">{answer || "No clear violations were identified in this guideline."}</p>

                          {sources.length > 0 && (
                            <div className="rounded-2xl bg-slate-50 border border-slate-200 p-4">
                              <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Guideline references</p>
                              <ul className="mt-2 space-y-2">
                                {sources.map((source: string, sourceIndex: number) => (
                                  <li key={sourceIndex} className="text-sm text-slate-700 flex gap-2">
                                    <span className="mt-1 h-1.5 w-1.5 rounded-full bg-slate-400 flex-shrink-0" />
                                    <span>{source}</span>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })
              ) : !analysisLoading && !analysisError ? (
                <div className="p-4 rounded-2xl bg-amber-50 border border-amber-200 text-sm text-amber-800">Upload a {mode} file and click Run Analysis to start asynchronous guideline checks.</div>
              ) : null}

              {remediationData && isRemediated ? (
                <div className="mt-6 space-y-3">
                  {mode === "text" ? (
                    <div className="space-y-3">
                      <div className="p-4 rounded-2xl bg-emerald-50 border border-emerald-200">
                        <p className="text-xs font-bold text-emerald-700 uppercase tracking-wide mb-2">Text remediated</p>
                        {showRemediatedText ? (
                          <div className="p-4 rounded-lg bg-white border border-emerald-200 max-h-60 overflow-y-auto">
                            <p className="text-sm text-slate-800 whitespace-pre-wrap break-words">{remediationData.remediated_text || "No remediated text available"}</p>
                          </div>
                        ) : (
                          <div className="p-3 rounded-lg bg-white border border-emerald-200"><p className="text-xs text-slate-600">Click below to view the remediated text</p></div>
                        )}
                      </div>

                      <button onClick={() => setShowRemediatedText(!showRemediatedText)} className="w-full bg-emerald-600 text-white py-3 rounded-xl font-bold hover:bg-emerald-700 transition-colors">{showRemediatedText ? "Hide Remediated Text" : "Show Remediated Text"}</button>
                      <button onClick={handleDownload} className="w-full bg-blue-500 text-white py-3 rounded-xl font-bold hover:bg-blue-600 transition-colors">Download Remediated Text</button>
                    </div>
                  ) : (
                    <>
                      {remediationStats && (
                        <div className="p-4 rounded-2xl bg-emerald-50 border border-emerald-200 space-y-2">
                          <p className="text-xs font-bold text-emerald-700 uppercase tracking-wide">Remediation complete</p>
                          {mode === "video" && remediationStats.total_frames && (
                            <>
                              <p className="text-[11px] text-slate-600"><span className="font-semibold">Frames processed:</span> {remediationStats.total_frames} total</p>
                              <p className="text-[11px] text-slate-600"><span className="font-semibold">Violations fixed:</span> {remediationStats.remediated_frames} frames</p>
                              {remediationStats.fps && <p className="text-[11px] text-slate-600"><span className="font-semibold">Resolution:</span> {remediationStats.width}x{remediationStats.height} @ {remediationStats.fps}fps</p>}
                            </>
                          )}
                          {mode === "audio" && remediationStats.total_beep_duration_sec !== undefined && <p className="text-[11px] text-slate-600"><span className="font-semibold">Beeped duration:</span> {remediationStats.total_beep_duration_sec}s</p>}
                          {mode === "image" && remediationStats.regions_blurred && <p className="text-[11px] text-slate-600"><span className="font-semibold">Regions blurred:</span> {remediationStats.regions_blurred}</p>}
                        </div>
                      )}
                      <button onClick={handleDownload} className="w-full bg-emerald-500 text-white py-3 rounded-xl font-bold hover:bg-emerald-600 transition-colors">Download Remediated {mode === "video" ? "Video" : mode === "audio" ? "Audio" : "Image"}</button>
                    </>
                  )}
                </div>
              ) : hasViolations ? (
                <div className="mt-6 space-y-3">
                  <div className="p-4 rounded-2xl bg-amber-50 border border-amber-200 text-sm text-amber-800 space-y-4">
                    <div>
                      <p className="font-semibold">Violations detected</p>
                      <p className="text-xs mt-1">Click below to run remediation for the detected violations.</p>
                    </div>

                  </div>

                  <button onClick={handleRemediate} disabled={isRemediating} className="w-full bg-amber-600 text-white py-3 rounded-xl font-bold hover:bg-amber-700 transition-colors disabled:opacity-50">{isRemediating ? "Remediating..." : "Run Remediation"}</button>
                </div>
              ) : (
                <div className="mt-6 p-4 rounded-2xl bg-amber-50 border border-amber-200 text-sm text-amber-800">
                  <p className="font-semibold">Remediation not available</p>
                  <p className="text-xs mt-1">Backend remediation is currently disabled or no violations were detected.</p>
                </div>
              )}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
