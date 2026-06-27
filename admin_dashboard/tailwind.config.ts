import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        lumi: {
          blue: "#2563EB",
          green: "#059669",
          surface: "#FFFFFF",
          muted: "#6B7280",
          border: "#E5E7EB",
          bg: "#F8FAFC",
        },
      },
    },
  },
  plugins: [],
};

export default config;
