"use client";
import React from 'react';
import { 
  ShieldCheck, TrendingUp, FileVideo, CheckCircle2, 
  AlertTriangle, DollarSign, ArrowUpRight, Shield, Globe 
} from 'lucide-react';

export default function AnalyticsPage() {
  return (
    <div className="min-h-screen bg-[#F8FAFC] p-10 font-[family-name:var(--font-geist-sans)] text-slate-900">
      
      {/* 1. TOP HEADER: ADAPTIVE STATUS */}
      <header className="max-w-6xl mx-auto mb-12 flex justify-between items-end">
        <div>
          <h1 className="text-4xl font-black tracking-tight text-slate-900">Impact Analytics</h1>
          <p className="text-slate-500 font-medium mt-2">Tracking the risks your AI has managed today.</p>
        </div>
        <div className="bg-white border border-slate-200 px-4 py-2 rounded-2xl shadow-sm flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
            Agentic RAG: Syncing Global Laws...
          </span>
        </div>
      </header>

      <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* 2. SAFETY SCORE */}
        <div className="lg:col-span-1 bg-white p-10 rounded-[3rem] shadow-xl shadow-slate-200/50 border border-slate-100 flex flex-col items-center text-center">
          <h3 className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.2em] mb-10">Brand Safety Score</h3>
          <div className="relative w-48 h-48 flex items-center justify-center">
            <svg className="w-full h-full -rotate-90">
              <circle cx="96" cy="96" r="88" stroke="currentColor" strokeWidth="12" fill="transparent" className="text-slate-50" />
              <circle cx="96" cy="96" r="88" stroke="currentColor" strokeWidth="12" fill="transparent" strokeDasharray="552" strokeDashoffset="33" className="text-indigo-600 transition-all duration-1000" />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-6xl font-black text-slate-900 leading-none">94</span>
              <span className="text-[10px] font-black text-emerald-500 uppercase mt-2 tracking-widest">Secure</span>
            </div>
          </div>
          <p className="mt-10 text-xs text-slate-400 font-bold uppercase tracking-tighter">
            System Adaptive: UAE Policy Sync Active
          </p>
        </div>

        {/* 3. CORE METRICS */}
        <div className="lg:col-span-2 grid grid-cols-1 md:grid-cols-2 gap-6">
          
          <div className="bg-white p-8 rounded-[2.5rem] border border-slate-100 shadow-sm flex flex-col justify-center">
            <div className="w-12 h-12 bg-indigo-50 rounded-2xl flex items-center justify-center mb-6">
              <FileVideo className="text-indigo-600 w-6 h-6" />
            </div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Medias Scanned/uploaded</p>
            <p className="text-5xl font-black text-slate-900 mt-2 tracking-tighter">1,542</p>
          </div>

          <div className="bg-white p-8 rounded-[2.5rem] border border-slate-100 shadow-sm flex flex-col justify-center">
            <div className="w-12 h-12 bg-emerald-50 rounded-2xl flex items-center justify-center mb-6">
              <CheckCircleIcon className="text-emerald-500 w-6 h-6" />
            </div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Issues Fixed/Medias Remediated</p>
            <p className="text-5xl font-black text-emerald-600 mt-2 tracking-tighter">1,128</p>
          </div>

          {/* 4. UPDATED: EST. FINES AVOIDED */}
          <div className="md:col-span-2 bg-slate-900 p-10 rounded-[3rem] text-white flex items-center justify-between shadow-2xl relative overflow-hidden">
            <div className="relative z-10">
              <div className="flex items-center gap-2 text-indigo-400 mb-4">
                <DollarSign className="w-5 h-5" />
                <span className="text-[10px] font-bold uppercase tracking-[0.3em]">Financial Impact</span>
              </div>
              <h3 className="text-3xl font-bold mb-2 tracking-tight">Est. Fines Avoided</h3>
              <p className="text-slate-400 text-xs font-medium max-w-sm leading-relaxed">
                Potential legal penalties prevented based on current 2026 global media benchmarks.
              </p>
            </div>
            <div className="text-right relative z-10">
              <p className="text-7xl font-black text-white tracking-tighter">$42,500</p>
              <div className="flex items-center justify-end gap-1 mt-4">
                <ArrowUpRight className="w-4 h-4 text-emerald-400" />
                <span className="text-emerald-400 text-[10px] font-bold uppercase tracking-widest bg-emerald-400/10 px-3 py-1.5 rounded-lg border border-emerald-400/20">
                  100% Risk Protected
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* 5. VIOLATION TIMELINE */}
        <div className="lg:col-span-3 bg-white p-12 rounded-[3.5rem] border border-slate-100 shadow-sm">
          <h3 className="text-2xl font-black text-slate-900 tracking-tight flex items-center gap-3 mb-10">
            <Shield className="text-amber-500 w-6 h-6" /> Where were the issues?
          </h3>
          
          <div className="space-y-6">
            <div className="h-4 w-full bg-slate-50 rounded-full relative overflow-hidden border border-slate-100">
              <div className="absolute left-[12%] top-0 h-full w-[4px] bg-red-500 shadow-md" />
              <div className="absolute left-[45%] top-0 h-full w-[4px] bg-amber-500 shadow-md" />
              <div className="absolute left-[78%] top-0 h-full w-[4px] bg-red-500 shadow-md" />
            </div>
            <div className="flex justify-between text-[10px] font-black text-slate-300 uppercase tracking-[0.2em]">
              <span>Start of Video</span>
              <span>Middle</span>
              <span>End of Video</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function CheckCircleIcon({ className }: any) { 
  return <CheckCircle2 className={className} />; 
}