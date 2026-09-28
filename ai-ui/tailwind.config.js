// SPDX-License-Identifier: MIT
export default {
  // Explicit 'class' strategy (not the implicit 'media' default): ai-ui has
  // no real dark theme or toggle today (packages/ecosystem-ui/src/theme.ts's
  // own comment; ai-ui/src/index.css hardcodes `color-scheme: light`) --
  // with no darkMode key at all, Tailwind defaults to 'media', so the
  // handful of pre-existing `dark:` utility classes (DocLivePreview.jsx,
  // Login.jsx) silently activated under prefers-color-scheme: dark, turning
  // some text light-gray while the background stayed white (illegible).
  // 'class' makes every `dark:` utility inert until something actually adds
  // a `.dark` class to the tree -- nothing does yet, so this only removes
  // the OS-driven breakage; it doesn't add or remove a real dark theme.
  darkMode: "class",
  content: [ "./index.html", "./src/**/*.{js,jsx}" ],
  theme: {
    extend: {
      animation: {
        fadeIn: "fadeIn 0.4s ease-in-out",
        shimmer: "shimmer 2s infinite linear",
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(100%)" },
        },
      },
    },
  },
  plugins: [ require( "@tailwindcss/typography" ) ],
};