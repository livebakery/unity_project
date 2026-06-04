import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        pitch: "#0b7a3b",
      },
    },
  },
  plugins: [],
} satisfies Config;
