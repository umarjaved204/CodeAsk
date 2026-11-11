// Round 1 review: message tone (F5) and one owner per message (F4).
import { expect, test } from "@playwright/test";

import type { Failure } from "../../lib/api";
import { connectionNote, isAlarm } from "../../lib/messages";
import type { Ask } from "../../lib/state";

const api = (code: string): Failure =>
  ({ kind: "api", status: 503, code, message: "", requestId: "a1b2c3d4", retryAfterS: null }) as Failure;
const unreachable: Failure = { kind: "unreachable" };

test("only failures on our side are alarms; limits, a removed repo and offline are calm", () => {
  for (const code of ["internal_error", "upstream_error", "timeout", "database_unavailable", "error"]) {
    expect(isAlarm(api(code), true), code).toBe(true);
  }
  for (const code of ["daily_cap", "model_unavailable", "not_found"]) {
    expect(isAlarm(api(code), true), code).toBe(false);
  }
  expect(isAlarm(unreachable, true)).toBe(true); // can't reach the server
  expect(isAlarm(unreachable, false)).toBe(false); // the visitor's own network
});

test("the composer's connection line is quiet when the question's own status explains it", () => {
  const asked = { repo: "a/b", question: "q?" };
  const offline = { kind: "offline" } as const;
  const failedOffline: Ask = { kind: "error", failure: unreachable, ...asked };
  const failedOnServer: Ask = { kind: "error", failure: api("internal_error"), ...asked };
  expect(connectionNote(offline, failedOffline, 0)).toBeNull();
  expect(connectionNote(offline, failedOnServer, 0)).toMatch(/^You're offline/);
  expect(connectionNote(offline, { kind: "idle", settling: null }, 0)).toMatch(/^You're offline/);
  expect(connectionNote({ kind: "up" }, failedOnServer, 0)).toBeNull();
});
