import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        page: "#f5fbff",
        skyglass: "#eaf6ff",
        ink: "#0f172a",
        vermilion: "#0ea5e9",
        pine: "#0369a1",
        brass: "#0f766e",
      },
      boxShadow: {
        soft: "0 18px 45px rgba(14, 116, 144, 0.1)",
      },
    },
  },
  plugins: [],
};

export default config;
