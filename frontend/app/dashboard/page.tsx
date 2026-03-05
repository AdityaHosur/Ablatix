"use client";
import React, { useState, useRef, useEffect } from 'react';
import Link from 'next/link'; // Added for navigation
import { 
  Upload, Youtube, Instagram, Twitter, Globe, CheckCircle2, ShieldCheck, 
  Zap, X, FileText, BarChart3, User, LogOut, ChevronUp 
} from 'lucide-react';

const PLATFORMS = [
  { id: 'youtube', name: 'YouTube', icon: <Youtube className="w-5 h-5 text-red-500" /> },
  { id: 'instagram', name: 'Instagram', icon: <Instagram className="w-5 h-5 text-pink-500" /> },
  { id: 'twitter', name: 'X / Twitter', icon: <Twitter className="w-5 h-5 text-slate-900" /> },
];

const COUNTRIES = ["India", "USA", "UAE", "UK", "Singapore"];

export default function ComplianceDashboard() {
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([]);
  const [selectedCountries, setSelectedCountries] = useState<string[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    return () => { if (previewUrl) URL.revokeObjectURL(previewUrl); };
  }, [previewUrl]);

  const toggle = (list: string[], setList: any, id: string) => {
    setList(list.includes(id) ? list.filter(x => x !== id) : [...list, id]);
  };

  const handleFile = (uploadedFile: File) => {
    setFile(uploadedFile);
    const url = URL.createObjectURL(uploadedFile);
    setPreviewUrl(url);
  };

  return (
    <div className="min-h-screen bg-slate-50 flex font-[family-name:var(--font-geist-sans)] text-slate-900">
      {/* SIDEBAR */}
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

        {/* --- PROFILE CIRCLE (BOTTOM) --- */}
        <div className="relative pt-6 border-t border-slate-100">
          <button 
            onClick={() => setIsProfileOpen(!isProfileOpen)} 
            className="w-full flex items-center gap-3 p-3 rounded-2xl hover:bg-slate-50 transition-all group"
          >
            <div className="w-10 h-10 rounded-full bg-indigo-600 flex items-center justify-center text-white font-bold shadow-lg border-2 border-white">DR</div>
            <div className="text-left flex-1">
              <p className="text-sm font-bold text-slate-900 leading-none">Dheer Raijada</p>
              <p className="text-[10px] text-emerald-500 font-bold uppercase mt-1 tracking-wider">Enterprise</p>
            </div>
            <ChevronUp className={`w-4 h-4 text-slate-300 transition-transform ${isProfileOpen ? 'rotate-0' : 'rotate-180'}`} />
          </button>

          {isProfileOpen && (
            <div className="absolute bottom-20 left-0 w-full bg-white rounded-3xl shadow-2xl border border-slate-100 p-2 z-50 animate-in slide-in-from-bottom-2">
              <Link 
                href="/analytics" // Navigates to your separate analytics page
                className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-bold text-slate-600 hover:bg-indigo-50 hover:text-indigo-600 transition-colors"
              >
                <BarChart3 className="w-4 h-4" /> View Analytics
              </Link>
              <div className="my-1 border-t border-slate-50" />
              <button className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-bold text-red-500 hover:bg-red-50 transition-colors">
                <LogOut className="w-4 h-4" /> Sign Out
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* MAIN CONTENT */}
      <main className="flex-1 ml-72 p-10 flex flex-col h-screen">
        <header className="flex justify-between items-center mb-8">
          <h2 className="text-2xl font-bold tracking-tight">Compliance Studio</h2>
          <button disabled={!file} className="bg-indigo-600 disabled:opacity-30 text-white px-6 py-3 rounded-xl font-bold shadow-lg shadow-indigo-100 flex items-center gap-2 hover:bg-indigo-700 transition-all">
            <Zap className="w-4 h-4 fill-white" /> Run Analysis
          </button>
        </header>

        <div 
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => { e.preventDefault(); setIsDragging(false); if(e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]); }}
          className={`flex-1 rounded-[2.5rem] border-2 border-dashed transition-all flex items-center justify-center relative overflow-hidden bg-white shadow-sm ${isDragging ? 'border-indigo-500 bg-indigo-50' : 'border-slate-200 hover:border-indigo-300'}`}
        >
          <input type="file" ref={fileInputRef} className="hidden" onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])} />
          {!file ? (
            <div className="text-center cursor-pointer" onClick={() => fileInputRef.current?.click()}>
              <div className="w-16 h-16 bg-indigo-50 rounded-2xl flex items-center justify-center mx-auto mb-4"><Upload className="text-indigo-600" /></div>
              <p className="font-bold text-slate-700">Drag & Drop Media</p>
              <p className="text-slate-400 text-sm mt-1 uppercase tracking-widest font-bold">Click to browse</p>
            </div>
          ) : (
            <div className="w-full h-full p-4 flex flex-col items-center">
              <button onClick={() => setFile(null)} className="absolute top-6 right-6 z-20 p-2 bg-white/80 backdrop-blur rounded-full shadow-md hover:text-red-500 transition-all"><X className="w-5 h-5" /></button>
              <div className="w-full h-full flex items-center justify-center rounded-2xl overflow-hidden bg-slate-900 shadow-inner">
                {file.type.startsWith('video/') ? <video src={previewUrl!} controls className="max-w-full max-h-full" /> : <img src={previewUrl!} alt="Preview" className="max-w-full max-h-full object-contain" />}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}