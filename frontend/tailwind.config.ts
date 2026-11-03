import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: ['class'],
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Dark, Linear-style palette: near-black ground, zinc greys, a mint accent.
        // Token names are kept from the earlier cream theme so every screen inherits it.
        background: '#09090b',
        paper: '#09090b',
        'paper-2': '#18181b',
        sunken: '#0e0e10',
        card: '#111113',
        foreground: '#fafafa',
        ink: '#fafafa',
        'ink-2': '#a1a1aa',
        'ink-3': '#8e8e96',
        'ink-4': '#63636b',
        border: '#27272a',
        'line-soft': '#1f1f23',
        forest: '#34d399',
        'forest-soft': '#14532d',
        'forest-tint': '#0f2a21',
        terracotta: '#fb923c',
        'terracotta-soft': '#5a2e0e',
        'terracotta-tint': '#2a1a0e',
        honey: '#fcd34d',
        rose: '#fda4af',
        primary: '#34d399',
        accent: '#fb923c',
        ok: '#6ee7b7',
        'ok-soft': '#0f2a21',
        warn: '#fdba74',
        'warn-soft': '#2a1b0c',
        bad: '#fca5a5',
        'bad-soft': '#2d1414',
        info: '#7dd3fc',
        'info-soft': '#0c2230'
      },
      fontFamily: {
        sans: ['Geist', 'Inter', '"Segoe UI"', 'sans-serif'],
        display: ['Geist', 'Inter', '"Segoe UI"', 'sans-serif'],
        mono: ['"Geist Mono"', 'ui-monospace', 'Menlo', 'monospace'],
        hebrew: ['Heebo', 'Geist', 'system-ui', 'sans-serif']
      },
      borderRadius: {
        sm: '6px',
        DEFAULT: '8px',
        lg: '14px',
        xl: '20px'
      },
      boxShadow: {
        soft: 'inset 0 1px 0 rgba(255, 255, 255, 0.04)',
        card: 'inset 0 1px 0 rgba(255, 255, 255, 0.04), 0 8px 24px -12px rgba(0, 0, 0, 0.6)',
        lift: 'inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 16px 40px -12px rgba(0, 0, 0, 0.7)'
      }
    }
  },
  plugins: []
};

export default config;
