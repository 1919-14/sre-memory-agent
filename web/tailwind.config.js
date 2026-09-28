/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    // Swiss style is strictly rectangular: no radius scale at all, so `rounded-*`
    // utilities cannot creep back in.
    borderRadius: {
      none: '0px',
      DEFAULT: '0px',
    },
    extend: {
      colors: {
        // Strict palette. Everything else is derived from these five values.
        ink: '#000000',
        paper: '#FFFFFF',
        muted: '#F2F2F2',
        accent: '#FF3000',
        line: '#000000',
        // Functional status colours. The brief requires these to be readable at a glance;
        // they are deliberately desaturated so they read as signals, not decoration.
        status: {
          ok: '#0B6B3A',
          warn: '#8A5A00',
          bad: '#FF3000',
          idle: '#5B5B5B',
          info: '#1A4FA0',
        },
        // Hairlines derived from ink at low opacity, for dense tabular data where a 2px
        // black rule for every row would be visually violent.
        hair: 'rgba(0,0,0,0.14)',
        'hair-strong': 'rgba(0,0,0,0.32)',
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
        mono: [
          'ui-monospace',
          'SFMono-Regular',
          'SF Mono',
          'Menlo',
          'Consolas',
          'Liberation Mono',
          'monospace',
        ],
      },
      fontSize: {
        // Mathematical scale with extreme contrast for headlines.
        label: ['0.6875rem', { lineHeight: '1', letterSpacing: '0.16em' }],
        micro: ['0.75rem', { lineHeight: '1.35' }],
        meta: ['0.8125rem', { lineHeight: '1.45' }],
        body: ['0.9375rem', { lineHeight: '1.6' }],
        lead: ['1.0625rem', { lineHeight: '1.55' }],
        h3: ['1.25rem', { lineHeight: '1.2', letterSpacing: '-0.01em' }],
        h2: ['1.75rem', { lineHeight: '1.1', letterSpacing: '-0.02em' }],
        h1: ['2.75rem', { lineHeight: '0.98', letterSpacing: '-0.03em' }],
        display: ['4.5rem', { lineHeight: '0.9', letterSpacing: '-0.045em' }],
        mega: ['7rem', { lineHeight: '0.85', letterSpacing: '-0.05em' }],
      },
      spacing: {
        // The documented spacing scale, so no arbitrary padding enters the codebase.
        18: '4.5rem',
        22: '5.5rem',
      },
      transitionTimingFunction: {
        swiss: 'cubic-bezier(0.2, 0, 0, 1)',
      },
      keyframes: {
        'fade-rise': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'scale-in': {
          from: { transform: 'scaleX(0)' },
          to: { transform: 'scaleX(1)' },
        },
        pulse: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.35' },
        },
      },
      animation: {
        'fade-rise': 'fade-rise 200ms cubic-bezier(0.2, 0, 0, 1) both',
        'scale-in': 'scale-in 320ms cubic-bezier(0.2, 0, 0, 1) both',
        'pulse-slow': 'pulse 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
