/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0c0d10',
        panel: '#141519',
        edge: '#23252b',
        ink: '#e8e9ec',
        dim: '#9195a1',
        good: '#4ade80',
        bad: '#f87171',
        warn: '#fbbf24',
        link: '#7dd3fc',
      },
    },
  },
  plugins: [],
};
