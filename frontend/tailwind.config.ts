/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: { extend: {
    colors: {
      neutral: { 50: '#f3f7f3', 100: 'rgb(var(--foreground) / <alpha-value>)', 200: '#dce4dd', 300: '#c5d0c7', 400: 'rgb(var(--muted) / <alpha-value>)', 500: '#98a59c', 600: '#819087', 700: '#46564b', 800: 'rgb(var(--border) / <alpha-value>)', 900: 'rgb(var(--surface) / <alpha-value>)', 950: 'rgb(var(--background) / <alpha-value>)' },
      blue: { 100: '#e4f3d8', 200: '#d7edc3', 300: '#cbeaaf', 400: '#c4ef99', 500: '#b3dd89', 600: '#b9e78e', 700: '#92b871', 900: '#293822', 950: '#1c2917' },
      indigo: { 400: '#c4ef99', 500: '#b3dd89' },
    },
  } },
  darkMode: 'class',
}
