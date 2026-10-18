import React from 'react';
import LandingNavbar from './LandingNavbar';
import LandingFooter from './LandingFooter';

export default function Layout({ children }) {
  return (
    <div className="mep-shell min-h-screen min-w-0 flex flex-col text-white">
      <LandingNavbar />
      <main className="mep-page min-w-0 flex-grow pt-16">
        {children}
      </main>
      <LandingFooter />
    </div>
  );
}
