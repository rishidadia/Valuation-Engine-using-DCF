/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#07080a",
          900: "#0a0b0e",
          850: "#0d0f13",
          800: "#12141a",
          700: "#1a1d25",
          600: "#242833",
        },
        line: "#1e222c",
        muted: "#878e9c",
        dim: "#5c6371",
        accent: {
          DEFAULT: "#58d6a9",
          dim: "#2f8f70",
          bright: "#7ff0c8",
        },
        up: "#4ade80",
        down: "#f87171",
        warn: "#fbbf24",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      letterSpacing: {
        widest2: "0.18em",
      },
      animation: {
        "fade-in": "fadeIn 0.25s ease-out",
        "pulse-once": "pulseOnce 0.6s ease-in-out 1",
        "slide-up": "slideUp 0.35s cubic-bezier(0.22, 1, 0.36, 1) both",
        "slide-in-right": "slideInRight 0.3s cubic-bezier(0.22, 1, 0.36, 1) both",
        "scale-in": "scaleIn 0.2s ease-out both",
      },
      keyframes: {
        fadeIn: { from: { opacity: "0", transform: "translateY(2px)" }, to: { opacity: "1", transform: "none" } },
        pulseOnce: { "0%": { opacity: "0.4" }, "100%": { opacity: "1" } },
        slideUp: { from: { opacity: "0", transform: "translateY(10px)" }, to: { opacity: "1", transform: "none" } },
        slideInRight: { from: { opacity: "0", transform: "translateX(12px)" }, to: { opacity: "1", transform: "none" } },
        scaleIn: { from: { opacity: "0", transform: "scale(0.96)" }, to: { opacity: "1", transform: "scale(1)" } },
      },
    },
  },
  plugins: [],
};
