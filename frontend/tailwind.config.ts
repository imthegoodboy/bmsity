import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        page: "#f5f7f2",
        skyglass: "#eef7f8",
        ink: "#172033",
        vermilion: "#c73d2f",
        pine: "#0f6b5f",
        brass: "#b7771c",
      },
      boxShadow: {
        soft: "0 18px 45px rgba(23, 32, 51, 0.08)",
      },
    },
  },
  plugins: [],
};

export default config;
