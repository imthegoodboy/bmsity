import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        skyglass: "#eff8ff",
        ink: "#172033",
      },
      boxShadow: {
        soft: "0 18px 45px rgba(37, 99, 235, 0.08)",
      },
    },
  },
  plugins: [],
};

export default config;
