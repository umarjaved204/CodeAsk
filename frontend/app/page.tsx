import { preconnect } from "react-dom";

import { App } from "../components/App";
import { readSiteConfig } from "../lib/site-config";

// Every visit starts with GET /status to the API: open its connection (DNS, TLS) while the page's
// JavaScript loads (Q81). Only here: /privacy makes no API calls. crossOrigin matches the
// page's CORS fetches, which use the anonymous connection pool.
const { apiOrigin } = readSiteConfig(process.env, process.env.NODE_ENV === "production");

export default function Home() {
  if (apiOrigin) preconnect(apiOrigin, { crossOrigin: "anonymous" });
  return <App />;
}
