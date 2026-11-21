import { describe, expect, it } from "vitest";
import { runBlockReason } from "./runState.js";

const ok = { fileCount: 1, jobStatus: null, sending: false };

describe("Run button", () => {
  it("is enabled whenever a file is selected and no job is running", () => {
    expect(runBlockReason(ok)).toBe("");
    expect(runBlockReason({ ...ok, fileCount: 40 })).toBe("");
    expect(runBlockReason({ ...ok, jobStatus: "done" })).toBe("");
    expect(runBlockReason({ ...ok, jobStatus: "failed" })).toBe("");
  });
  it("is disabled while a job is running or uploading, with the reason", () => {
    expect(runBlockReason({ ...ok, jobStatus: "queued" })).toBe("A job is running");
    expect(runBlockReason({ ...ok, jobStatus: "processing" })).toBe("A job is running");
    expect(runBlockReason({ ...ok, sending: true })).toBe("Uploading…");
  });
  it("is disabled with no file selected", () => {
    expect(runBlockReason({ ...ok, fileCount: 0 })).toBe("Select at least one file");
  });
});
