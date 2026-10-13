import type { Metadata } from 'next';

import { InstructorAuthGate } from '@/components/instructor-auth-gate';

import './globals.css';

export const metadata: Metadata = {
  title: 'course-grader',
  description: 'Localhost grading system for multi-course applied AI assessment'
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Newsreader:opsz,wght@6..72,400;6..72,500&family=JetBrains+Mono:wght@400;500&family=Frank+Ruhl+Libre:wght@400;500;700&display=swap"
        />
      </head>
      <body>
        {children}
        <InstructorAuthGate />
      </body>
    </html>
  );
}
