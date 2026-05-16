import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  safelist: [
    { pattern: /^bg-zone-(external|perimeter|dmz|internal|restricted|management)$/ },
    { pattern: /^text-zone-(external|perimeter|dmz|internal|restricted|management)$/ },
    { pattern: /^border-zone-(external|perimeter|dmz|internal|restricted|management)$/ },
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#00518F",
          50: "#e6eef5",
          100: "#cdddeb",
          200: "#9bbbd7",
          300: "#6999c3",
          400: "#3777af",
          500: "#00518F",
          600: "#004273",
          700: "#003258",
          800: "#00213c",
          900: "#001120",
        },
        zone: {
          external: "#ef4444",
          perimeter: "#f59e0b",
          dmz: "#eab308",
          internal: "#22c55e",
          restricted: "#3b82f6",
          management: "#a855f7",
        },
        flow: {
          ns: "#f97316",
          ew: "#0ea5e9",
        },
      },
      fontFamily: {
        sans: [
          "Inter", "ui-sans-serif", "system-ui", "-apple-system",
          "Segoe UI", "Roboto", "sans-serif",
        ],
        mono: [
          "ui-monospace", "SFMono-Regular", "Menlo", "Monaco",
          "Consolas", "monospace",
        ],
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(0 0 0 / 0.04), 0 1px 3px 0 rgb(0 0 0 / 0.06)",
        elev: "0 4px 12px -2px rgb(0 0 0 / 0.08), 0 2px 6px -1px rgb(0 0 0 / 0.06)",
      },
    },
  },
  plugins: [],
} satisfies Config;
