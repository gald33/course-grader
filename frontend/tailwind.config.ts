import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: ['class'],
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Warm cream palette evolved from the original cream/teal/amber.
        background: '#f5f1e8',
        paper: '#f5f1e8',
        'paper-2': '#efe9dc',
        card: '#fdfbf6',
        foreground: '#2a2620',
        ink: '#2a2620',
        'ink-2': '#5b554b',
        'ink-3': '#8a8378',
        'ink-4': '#b6ad9e',
        border: '#e3dccd',
        'line-soft': '#ece5d4',
        forest: '#2d5d4f',
        'forest-soft': '#cee3da',
        'forest-tint': '#e8f1ec',
        terracotta: '#c97852',
        'terracotta-soft': '#f5d9c8',
        'terracotta-tint': '#fbe9dd',
        honey: '#d9a441',
        rose: '#c45a6b',
        primary: '#2d5d4f',
        accent: '#c97852',
        ok: '#4a7a5d',
        'ok-soft': '#d6e6db',
        warn: '#b8722f',
        'warn-soft': '#f3dfc4',
        bad: '#a44545',
        'bad-soft': '#ebcccb',
        info: '#4a6c7a',
        'info-soft': '#d4e0e6'
      },
      fontFamily: {
        sans: ['Inter', '"IBM Plex Sans"', '"Segoe UI"', 'sans-serif'],
        display: ['Newsreader', '"Source Serif Pro"', 'Georgia', 'serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'Menlo', 'monospace'],
        hebrew: ['"Frank Ruhl Libre"', 'Newsreader', 'system-ui', 'serif']
      },
      borderRadius: {
        sm: '6px',
        DEFAULT: '10px',
        lg: '16px',
        xl: '22px'
      },
      boxShadow: {
        soft: '0 1px 0 rgba(42, 38, 32, 0.04), 0 1px 2px rgba(42, 38, 32, 0.04)',
        card: '0 1px 0 rgba(42, 38, 32, 0.04), 0 4px 14px rgba(42, 38, 32, 0.06)',
        lift: '0 1px 0 rgba(42, 38, 32, 0.04), 0 8px 28px rgba(42, 38, 32, 0.08)'
      }
    }
  },
  plugins: []
};

export default config;
