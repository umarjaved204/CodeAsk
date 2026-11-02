// The three families of direction A (PLAN.md Q31), self-hosted by next/font: downloaded at
// build time and served from our own origin, so visitors' browsers never contact a font
// service. Latin subset only; display "swap" shows text in the fallback while a font loads.
import { Fragment_Mono, Instrument_Sans, Newsreader } from "next/font/google";

// Variable font, weight axis only: one file covers every weight. No optical-size axis (PLAN.md
// Q32): it made the Latin file 128.8 KB instead of 56.8 KB for a difference not worth it.
// Upright only: italics in an answer fall back to a synthesized slant (rare in answers, and
// saves a second file).
export const newsreader = Newsreader({
  subsets: ["latin"],
  display: "swap",
  style: ["normal"],
  variable: "--font-newsreader",
});

// Variable font (weight axis only): the interface uses 400, 500 and 600.
export const instrumentSans = Instrument_Sans({
  subsets: ["latin"],
  display: "swap",
  style: ["normal"],
  variable: "--font-instrument",
});

// Static font with a single weight: code only.
export const fragmentMono = Fragment_Mono({
  subsets: ["latin"],
  display: "swap",
  weight: "400",
  style: ["normal"],
  variable: "--font-fragment",
});
