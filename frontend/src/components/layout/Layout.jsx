import React from 'react';
import LandingNavbar from './LandingNavbar';
import LandingFooter from './LandingFooter';

export default function Layout({ children }) {
  return (
    <div className="min-h-screen min-w-0 flex flex-col bg-slate-950 text-white">
      <LandingNavbar />
      <main className="min-w-0 flex-grow pt-16">
        {children}
      </main>
      <LandingFooter />
    </div>
  );
}
