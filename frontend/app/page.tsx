"use client";
import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { ShieldCheck, ArrowRight, Lock, Mail, Building2, Radio, User } from "lucide-react";
import LoadingScanner from './components/LoadingScanner'; // Ensure this component exists

export default function AuthPage() {
  const [mode, setMode] = useState<'signup' | 'login'>('signup');
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  const handleAuth = (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    
    // Simulate AI scanning and law syncing before entering dashboard
    setTimeout(() => {
      router.push('/dashboard');
    }, 3500); 
  };

  if (isLoading) return <LoadingScanner />;

  return (
    <main className="min-h-screen bg-slate-50 flex items-center justify-center p-6 font-[family-name:var(--font-geist-sans)] text-slate-900">
      <div className="w-full max-w-md bg-white rounded-[2.5rem] shadow-2xl shadow-slate-200/60 p-10 border border-slate-100 animate-in fade-in zoom-in duration-300">
        
        {/* HEADER */}
        <div className="flex flex-col items-center mb-8">
          <div className="p-4 bg-indigo-600 rounded-2xl mb-4 shadow-lg shadow-indigo-200">
            <ShieldCheck className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight text-center">
            {mode === 'signup' ? 'Join Ablatix' : 'Welcome Back'}
          </h1>
          <p className="text-slate-500 text-sm mt-1 text-center font-medium px-4">
            {mode === 'signup' 
              ? 'Create your secure workspace for content compliance.' 
              : 'Login to access your compliance insights.'}
          </p>
        </div>

        {/* FORM */}
        <form className="space-y-4" onSubmit={handleAuth}>
          {mode === 'signup' && (
            <>
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-slate-400 uppercase ml-1 tracking-wider">Company / Agency</label>
                <div className="relative">
                  <Building2 className="absolute left-4 top-3.5 w-5 h-5 text-slate-300" />
                  <input required type="text" placeholder="Brand Marketing team" className="w-full pl-12 pr-4 py-3.5 rounded-2xl bg-slate-50 border border-slate-100 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 outline-none transition-all font-medium text-slate-700" />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-bold text-slate-400 uppercase ml-1 tracking-wider">Channel Handle</label>
                <div className="relative">
                  <Radio className="absolute left-4 top-3.5 w-5 h-5 text-slate-300" />
                  <input required type="text" placeholder="@BrandChannel" className="w-full pl-12 pr-4 py-3.5 rounded-2xl bg-slate-50 border border-slate-100 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 outline-none transition-all font-medium text-slate-700" />
                </div>
              </div>
            </>
          )}

          <div className="space-y-1">
            <label className="text-[10px] font-bold text-slate-400 uppercase ml-1 tracking-wider">Work Email</label>
            <div className="relative">
              <Mail className="absolute left-4 top-3.5 w-5 h-5 text-slate-300" />
              <input required type="email" placeholder="name@company.com" className="w-full pl-12 pr-4 py-3.5 rounded-2xl bg-slate-50 border border-slate-100 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 outline-none transition-all font-medium text-slate-700" />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-[10px] font-bold text-slate-400 uppercase ml-1 tracking-wider">Password</label>
            <div className="relative">
              <Lock className="absolute left-4 top-3.5 w-5 h-5 text-slate-300" />
              <input required type="password" placeholder="••••••••" className="w-full pl-12 pr-4 py-3.5 rounded-2xl bg-slate-50 border border-slate-100 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 outline-none transition-all font-medium text-slate-700" />
            </div>
          </div>

          <button type="submit" className="w-full bg-slate-900 text-white py-4 rounded-2xl font-bold flex items-center justify-center gap-2 hover:bg-slate-800 transition-all shadow-xl shadow-slate-200 mt-6 group">
            {mode === 'signup' ? 'Create Workspace' : 'Sign In to your Workspace'} 
            <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
          </button>
        </form>

        {/* SWITCHER */}
        <div className="mt-8 text-center">
          <p className="text-sm text-slate-500 font-medium">
            {mode === 'signup' ? 'Already a member?' : 'New to Ablatix?'}
            <button 
              onClick={() => setMode(mode === 'signup' ? 'login' : 'signup')}
              className="ml-2 text-indigo-600 font-bold hover:underline"
            >
              {mode === 'signup' ? 'Login' : 'Create an Account'}
            </button>
          </p>
        </div>
      </div>
    </main>
  );
}