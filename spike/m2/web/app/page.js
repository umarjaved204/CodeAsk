"use client";

// M2-0 spike: calls the API straight from the browser and times each call.
import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL;
const CALLS = ["/health", "/db", "/search", "/slow?s=60", "/boom"];

export default function Home() {
  const [log, setLog] = useState([]);

  async function call(path) {
    const started = new Date().toLocaleTimeString();
    const t0 = performance.now();
    let result;
    try {
      const res = await fetch(API + path);
      const firstByte = Math.round(performance.now() - t0);
      result = `${res.status} first byte ${firstByte} ms\n${await res.text()}`;
    } catch (err) {
      result = `FAILED after ${Math.round(performance.now() - t0)} ms: ${err}`;
    }
    setLog((l) => [`[${started}] ${path}\n${result}`, ...l]);
  }

  return (
    <main>
      <h1>CodeAsk M2-0 spike</h1>
      <p>API: {API || "NEXT_PUBLIC_API_URL is not set"}</p>
      {CALLS.map((p) => (
        <button key={p} onClick={() => call(p)} style={{ marginRight: 8 }}>
          {p}
        </button>
      ))}
      <pre style={{ whiteSpace: "pre-wrap" }}>{log.join("\n\n")}</pre>
    </main>
  );
}
