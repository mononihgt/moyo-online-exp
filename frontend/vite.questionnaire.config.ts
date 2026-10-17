import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    outDir: "dist-questionnaire",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        questionnaire: resolve(__dirname, "questionnaire.html"),
      },
    },
  },
});
