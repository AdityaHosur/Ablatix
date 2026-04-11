"use client";
import React, { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import {
Upload, Youtube, Instagram, Twitter, CheckCircle2, ShieldCheck,
Zap, X, BarChart3, LogOut, ChevronUp
} from 'lucide-react';

const PLATFORMS = [
{ id: 'youtube', name: 'YouTube', icon: <Youtube className="w-5 h-5 text-red-500" /> },
{ id: 'instagram', name: 'Instagram', icon: <Instagram className="w-5 h-5 text-pink-500" /> },
{ id: 'twitter', name: 'X / Twitter', icon: <Twitter className="w-5 h-5 text-slate-900" /> },
];

const COUNTRIES = ["India", "USA", "UAE", "UK", "Singapore"];

export default function ComplianceDashboard() {
  const [mounted, setMounted] = useState(false);

useEffect(() => {
  setMounted(true);
}, []);
const [isProfileOpen, setIsProfileOpen] = useState(false);
const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([]);
const [selectedCountries, setSelectedCountries] = useState<string[]>([]);
const [file, setFile] = useState<File | null>(null);
const [previewUrl, setPreviewUrl] = useState<string | null>(null);
const [isDragging, setIsDragging] = useState(false);

const [mode, setMode] = useState<"image" | "video" | "text">("image");
const [textInput, setTextInput] = useState("");

const [showResults, setShowResults] = useState(false);
const [isRemediating, setIsRemediating] = useState(false);
const [isRemediated, setIsRemediated] = useState(false);


const [progress, setProgress] = useState(0);

const fileInputRef = useRef<HTMLInputElement>(null);

useEffect(() => {
return () => { if (previewUrl) URL.revokeObjectURL(previewUrl); };
}, [previewUrl]);

const toggle = (list: string[], setList: any, id: string) => {
setList(list.includes(id) ? list.filter(x => x !== id) : [...list, id]);
};

const handleFile = (uploadedFile: File) => {
if (
(mode === "image" && !uploadedFile.type.startsWith("image/")) ||
(mode === "video" && !uploadedFile.type.startsWith("video/"))
) {
alert("Invalid file type selected");
return;
}


setFile(uploadedFile);
const url = URL.createObjectURL(uploadedFile);
setPreviewUrl(url);


setIsRemediated(false);
setShowResults(false);
setProgress(0);


};

const handleDownload = () => {
if (mode === "text") {
const blob = new Blob([textInput], { type: "text/plain" });
const url = URL.createObjectURL(blob);
const a = document.createElement("a");
a.href = url;
a.download = "remediated.txt";
a.click();
} else if (previewUrl) {
const a = document.createElement("a");
a.href = previewUrl;
a.download = `remediated.${mode === "video" ? "mp4" : "png"}`;
a.click();
}
};

const [user, setUser] = useState<any>(null);

useEffect(() => {
  const u = localStorage.getItem("user");
  if (u) setUser(JSON.parse(u));
}, []);

const getInitials = (name: string) => {
  return name
    ?.split(" ")
    .map(word => word[0])
    .join("")
    .toUpperCase();
};
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
          {PLATFORMS.map(p => (
            <button key={p.id} onClick={() => toggle(selectedPlatforms, setSelectedPlatforms, p.id)} className={`w-full flex items-center justify-between p-3 rounded-xl border-2 transition-all ${selectedPlatforms.includes(p.id) ? 'border-indigo-600 bg-indigo-50' : 'border-slate-50 bg-white hover:border-slate-200'}`}>
              <div className="flex items-center gap-2">{p.icon} <span className="text-sm font-semibold text-slate-700">{p.name}</span></div>
              {selectedPlatforms.includes(p.id) && <CheckCircle2 className="w-4 h-4 text-indigo-600 fill-indigo-50" />}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="text-[10px] font-bold text-slate-400 uppercase tracking-widest block mb-4">Target Regions</label>
        <div className="flex flex-wrap gap-2">
          {COUNTRIES.map(c => (
            <button key={c} onClick={() => toggle(selectedCountries, setSelectedCountries, c)} className={`px-3 py-1.5 rounded-full border text-[11px] font-bold transition-all ${selectedCountries.includes(c) ? 'bg-slate-900 text-white' : 'bg-white text-slate-500 hover:border-slate-400'}`}>
              {c}
            </button>
          ))}
        </div>
      </div>
    </div>

    <div className="relative pt-6 border-t border-slate-100">
      <button onClick={() => setIsProfileOpen(!isProfileOpen)} className="w-full flex items-center gap-3 p-3 rounded-2xl hover:bg-slate-50">
        <div className="w-10 h-10 rounded-full bg-indigo-600 flex items-center justify-center text-white font-bold">
  {!mounted ? "DR" : user ? getInitials(user.name) : "DR"}
</div>

<div className="text-left flex-1">
  
    <p className="text-sm font-bold text-slate-900">
  {!mounted ? "User" : user ? user.name : "User"}
</p>
  
</div>


        <ChevronUp />
      </button>
      {isProfileOpen && (
  <div className="absolute bottom-20 left-0 w-full bg-white rounded-3xl shadow-2xl border p-2">
    
    <Link href="/analytics" className="flex items-center gap-3 px-4 py-3 text-sm font-bold text-slate-600 hover:bg-indigo-50">
      <BarChart3 /> View Analytics
    </Link>

    <button
  onClick={() => {
    window.location.href = "/"; 
  }}
  className="flex items-center gap-3 px-4 py-3 text-sm font-bold text-red-500 hover:bg-red-50"
>
  <LogOut /> Sign Out
</button>

  </div>
)}
    </div>
  </aside>

  <main className="flex-1 ml-72 p-10 flex h-screen gap-6">

    <div className="flex-1 flex flex-col">

      <header className="flex justify-between items-center mb-4">

  <div>
    <h2 className="text-2xl font-bold tracking-tight">
      Compliance Studio
    </h2>

    {mounted && user && (
      <h3 className="text-sm font-semibold text-indigo-600 mt-1">
        Welcome to {user.name}'s Workspace
      </h3>
    )}
  </div>

  <button
    onClick={() => { setShowResults(true); setIsRemediated(false); }}
    disabled={mode === "text" ? !textInput : !file}
    className="bg-indigo-600 disabled:opacity-30 text-white px-6 py-3 rounded-xl font-bold flex items-center gap-2"
  >
    <Zap /> Run Analysis
  </button>

</header>

      <div className="flex gap-3 mb-6">
        {["image", "video", "text"].map((m) => (
          <button key={m} onClick={() => {
            setMode(m as any);
            setFile(null);
            setTextInput("");
            setIsRemediated(false);
            setShowResults(false);
            setProgress(0);
          }}
            className={`px-4 py-2 rounded-xl font-bold capitalize border transition-all ${mode === m ? 'border-indigo-600 bg-indigo-50 text-indigo-600' : 'border-slate-200 text-slate-500 hover:border-slate-400'}`}>
            {m}
          </button>
        ))}
      </div>

      {mode === "text" ? (
        <div className="flex-1 rounded-[2.5rem] border border-slate-200 bg-white shadow-sm p-6 relative transition-all hover:border-indigo-300">

          {isRemediating && (
            <div className="absolute inset-0 pointer-events-none flex items-center justify-center">
              <div className="absolute inset-0 bg-indigo-500/10" />
              <div className="absolute w-full h-24 bg-gradient-to-b from-transparent via-indigo-400/40 to-transparent animate-scan" />
              <div className="relative z-10 bg-white/70 backdrop-blur px-6 py-3 rounded-xl shadow text-indigo-600 font-bold">
                {progress}%
              </div>
            </div>
          )}

          <textarea
            value={textInput}
            onChange={(e) => {
  const value = e.target.value;
  setTextInput(value);

  //  If text becomes empty → reset everything
  if (value.trim() === "") {
    setShowResults(false);
    setIsRemediated(false);
    setIsRemediating(false);
    setProgress(0);
  }
}}
            placeholder="Enter the text..."
            className="w-full h-full outline-none text-slate-700 resize-none"
          />
        </div>
      ) : (
        <div
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => { e.preventDefault(); setIsDragging(false); if(e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]); }}
          className={`flex-1 rounded-[2.5rem] border-2 border-dashed transition-all flex items-center justify-center relative overflow-hidden bg-white shadow-sm ${isDragging ? 'border-indigo-500 bg-indigo-50' : 'border-slate-200 hover:border-indigo-300'}`}
        >

          {isRemediating && (
            <div className="absolute inset-0 pointer-events-none flex items-center justify-center">
              <div className="absolute inset-0 bg-indigo-500/10" />
              <div className="absolute w-full h-24 bg-gradient-to-b from-transparent via-indigo-400/40 to-transparent animate-scan" />
              <div className="relative z-10 bg-white/70 backdrop-blur px-6 py-3 rounded-xl shadow text-indigo-600 font-bold">
                {progress}%
              </div>
            </div>
          )}

          <input type="file"
            accept={mode === "image" ? "image/*" : "video/*"}
            ref={fileInputRef}
            className="hidden"
            onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
          />

          {!file ? (
            <div className="text-center cursor-pointer" onClick={() => fileInputRef.current?.click()}>
              <div className="w-16 h-16 bg-indigo-50 rounded-2xl flex items-center justify-center mx-auto mb-4">
                <Upload className="text-indigo-600" />
              </div>
              <p className="font-bold text-slate-700">
                Drag & Drop {mode === "image" ? "Image" : "Video"}
              </p>
              <p className="text-slate-400 text-sm mt-1 uppercase tracking-widest font-bold">
                Click to browse
              </p>
            </div>
          ) : (
            <div className="w-full h-full p-4 flex flex-col items-center">
              <button
  onClick={() => {
    setFile(null);

    
    setShowResults(false);
    setIsRemediated(false);
    setIsRemediating(false);
    setProgress(0);
  }}
  className="absolute top-6 right-6 z-20 p-2 bg-white/80 backdrop-blur rounded-full shadow-md hover:text-red-500"
>
  <X />
</button>

              <div className="w-full h-full flex items-center justify-center rounded-2xl overflow-hidden bg-slate-900 shadow-inner">
                {mode === "video"
                  ? <video src={previewUrl!} controls className="max-w-full max-h-full" />
                  : <img src={previewUrl!} alt="Preview" className="max-w-full max-h-full object-contain" />
                }
              </div>
            </div>
          )}
        </div>
      )}
    </div>

    {showResults && (
      <div className="w-[380px] bg-white border border-slate-200 rounded-[2.5rem] shadow-sm p-6 flex flex-col">
        <h3 className="font-bold mb-4">Detected Violations</h3>

        <div className="flex-1 space-y-3">
          {[{ time: "00:05", text: "Violation detected" }].map((v, i) => (
            <div key={i} className="p-3 rounded-xl bg-red-50 border border-red-200">
              <p className="text-xs text-red-500 font-bold">{v.time}</p>
              <p>{v.text}</p>
            </div>
          ))}
        </div>

        {!isRemediated ? (
          <button
            onClick={() => {
              setIsRemediating(true);
              setProgress(0);

              let fake = 0;
              const interval = setInterval(() => {
                fake += Math.random() * 15;

                if (fake >= 100) {
                  fake = 100;
                  clearInterval(interval);

                  setTimeout(() => {
                    setIsRemediating(false);
                    setIsRemediated(true);
                  }, 300);
                }

                setProgress(Math.floor(fake));
              }, 200);
            }}
            className="mt-4 bg-red-500 text-white py-3 rounded-xl font-bold"
          >
            Remediate {mode}
          </button>
        ) : (
          <button onClick={handleDownload} className="mt-4 bg-emerald-500 text-white py-3 rounded-xl font-bold">
            Download Remediated {mode}
          </button>
        )}
      </div>
    )}

  </main>
</div>


);
}
