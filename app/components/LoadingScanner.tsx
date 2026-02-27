"use client";
import React from 'react';
import { ShieldCheck, FileVideo, Zap, CheckCircle2 } from 'lucide-react';

export default function LoadingScanner() {
  return (
    <div className="fixed inset-0 bg-white z-[100] flex flex-col items-center justify-center p-6 text-center animate-in fade-in duration-500">
      <div className="relative w-48 h-48 mb-10">
        {/* THE VIDEO ICON */}
        <div className="absolute inset-0 flex items-center justify-center bg-indigo-50 rounded-[2.5rem] border-2 border-indigo-100 shadow-inner">
          <FileVideo className="w-20 h-20 text-indigo-400" />
        </div>

        {/* THE SCANNING BEAM */}
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-indigo-500/20 to-transparent h-12 w-full animate-scan pointer-events-none border-t border-indigo-400/50" />
        
        {/* REMEDIATION GLOW */}
        <div className="absolute inset-0 rounded-[2.5rem] animate-pulse border-4 border-emerald-400/0 hover:border-emerald-400/50 transition-all duration-1000" />
      </div>

      <div className="space-y-4 max-w-sm">
        <h2 className="text-2xl font-black text-slate-900 tracking-tight flex items-center justify-center gap-2">
           Initializing Ablatix
        </h2>
        
        {/* LOGIC STEPS ANIMATION */}
        <div className="space-y-3">
          <p className="text-slate-400 text-xs font-bold uppercase tracking-widest animate-pulse">
            Connecting Agentic RAG...
          </p>
          <div className="w-full bg-slate-100 h-1.5 rounded-full overflow-hidden">
            <div className="bg-indigo-600 h-full w-full animate-progress-fast origin-left" />
          </div>
        </div>

        <div className="flex justify-center gap-8 mt-6">
           <div className="flex flex-col items-center opacity-40 animate-bounce duration-700">
             <ShieldCheck className="w-5 h-5 text-indigo-600" />
             <span className="text-[10px] font-bold mt-1 uppercase">Scan</span>
           </div>
           <div className="flex flex-col items-center opacity-40 animate-bounce duration-1000">
             <Zap className="w-5 h-5 text-indigo-600" />
             <span className="text-[10px] font-bold mt-1 uppercase">Remediate</span>
           </div>
           <div className="flex flex-col items-center opacity-40 animate-bounce duration-500">
             <CheckCircle2 className="w-5 h-5 text-indigo-600" />
             <span className="text-[10px] font-bold mt-1 uppercase">Verified</span>
           </div>
        </div>
      </div>

      <style jsx>{`
        @keyframes scan {
          0% { top: 0; }
          100% { top: 75%; }
        }
        .animate-scan {
          position: absolute;
          animation: scan 2s linear infinite;
        }
        @keyframes progress {
          0% { transform: scaleX(0); }
          100% { transform: scaleX(1); }
        }
        .animate-progress-fast {
          animation: progress 3s ease-out forwards;
        }
      `}</style>
    </div>
  );
}