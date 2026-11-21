import { describe, expect, it } from "vitest";
import { renderToStaticMarkup as html } from "react-dom/server";
import ResultsCard from "./components/ResultsCard.jsx";
import TopBar from "./components/TopBar.jsx";

const job = { status: "done", processed: 2, total: 2 };
const results = [
  { file_name: "a.jpg", page: null, status: "ok", error: "", R: 220.02, G: 140, B: 40, predicted_concentration_ppm: 199.6, typical_error_ppm: 12.5, flags: "", warning: "", image_url: null },
  { file_name: "b.pdf", page: 2, status: "failed", error: "no tube", R: null, G: null, B: null, predicted_concentration_ppm: null, typical_error_ppm: null, flags: "failed", warning: "", image_url: null },
];

describe("Top bar", () => {
  it("never shows a model status, whatever the model state is", () => {
    const m = html(<TopBar dbDown={false} backendError={null} />);
    expect(m).toContain("RGB measurement");
    for (const text of ["No model", "train one", "Model:", "Checking the model", "CSV or XLSX"]) expect(m).not.toContain(text);
    expect(m).not.toMatch(/class="chip /);                   // no chip at all when everything is fine
  });
  it("shows a red chip only when the database or the backend is down", () => {
    expect(html(<TopBar dbDown backendError={null} />)).toMatch(/class="chip bad"[^>]*>.*Database not reachable/);
    expect(html(<TopBar dbDown={false} backendError={{ message: "The backend is not reachable. Is it running?" }} />)).toContain("The backend is not reachable");
  });
});

describe("Results table", () => {
  it("has the requested columns in order", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={results} hasModel />);
    const heads = [...m.matchAll(/<th class="[^"]*">([^<]*)<\/th>/g)].map((x) => x[1]);
    expect(heads).toEqual(["#", "File", "Page", "R", "G", "B", "Colour", "Predicted concentration (ppm)", "± error (ppm)", "Status", "Flags", "Notes", "Image"]);
  });
  it("shows the prediction when a model is loaded", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={results} hasModel />);
    expect(m).toMatch(/<td class="c-ppm num">199\.6<\/td><td class="c-err num">12\.5<\/td>/);
    expect(m).not.toContain("No model loaded");
  });
  it("shows a dash with a tooltip when there is no model", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={results} hasModel={false} />);
    expect((m.match(/<td class="c-(?:ppm|err) num" title="No model loaded">—<\/td>/g) || []).length).toBe(4);
    expect(m).toMatch(/>220\.02<\/td><td class="c-rgb num">140\.00<\/td><td class="c-rgb num">40\.00</);   // R, G, B are always shown
  });
  it("shows the measured colour as a swatch, clamped to 0-255", () => {
    const wild = [{ ...results[0], R: 300.4, G: -5, B: 40.4 }];
    const m = html(<ResultsCard jobId="j" job={job} results={wild} hasModel />);
    expect(m).toContain("background:rgb(255, 0, 40)");
    expect(html(<ResultsCard jobId="j" job={job} results={[results[1]]} hasModel />)).not.toContain("swatch");   // failed row: no colour
  });
  it("shows status pills and flag tags", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={[{ ...results[0], status: "low_pixels", flags: "low_pixels;clipped" }, results[1]]} hasModel />);
    expect(m).toContain('<span class="pill warn">Low pixels</span>');
    expect(m).toContain('<span class="pill bad">Failed</span>');
    expect(m).toContain('<span class="tag">clipped</span>');
    expect(html(<ResultsCard jobId="j" job={job} results={results} hasModel />)).toContain('<span class="pill ok">OK</span>');
  });
  it("shows the status pill and the three figures in one summary row, with their labels apart", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={results} hasModel />);
    const row = m.match(/<div class="summary">.*?<\/div>/s)[0];
    expect(row).toContain('<span class="pill ok">done</span>');
    expect(row).toContain('<span class="figure"><b class="mono">2</b><span>rows</span></span>');
    expect(row).toContain('<span class="figure"><b class="mono">1</b><span>failed</span></span>');
    expect(row).toContain('<span class="figure"><b class="mono">0</b><span>flagged</span></span>');
    expect(row.indexOf("pill")).toBeLessThan(row.indexOf("rows"));
    expect(m).not.toContain('class="stats"');
  });
  it("uses the singular for exactly one row", () => {
    const one = html(<ResultsCard jobId="j" job={job} results={[results[0]]} hasModel />);
    expect(one).toContain('<b class="mono">1</b><span>row</span>');
    expect(one).not.toContain("<span>rows</span>");
    expect(html(<ResultsCard jobId="j" job={job} results={[]} hasModel />)).toContain('<b class="mono">0</b><span>rows</span>');
  });
  it("colours the pill by state: done green, processing amber, failed red", () => {
    const pill = (status) => html(<ResultsCard jobId="j" job={{ status, processed: 3, total: 15 }} results={results} hasModel />).match(/<span class="(pill [a-z]+)">([a-z]+)<\/span>/)[0];
    expect(pill("done")).toBe('<span class="pill ok">done</span>');
    expect(pill("processing")).toBe('<span class="pill warn">processing</span>');
    expect(pill("failed")).toBe('<span class="pill bad">failed</span>');
  });
  it("shows the progress count in the row while processing", () => {
    const m = html(<ResultsCard jobId="j" job={{ status: "processing", processed: 3, total: 15 }} results={results} hasModel />);
    expect(m).toContain("3/15 processed");
    expect(html(<ResultsCard jobId="j" job={job} results={results} hasModel />)).not.toContain("processed");
  });
  it("shows a centred empty state before any job", () => {
    const m = html(<ResultsCard jobId={null} job={null} results={[]} hasModel={false} />);
    expect(m).toContain('class="empty"');
    expect(m).toContain("Results appear here after you press Run.");
  });
  it("gives every column a class, so the styles do not depend on the column position", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={results} hasModel />);
    const headClasses = [...m.matchAll(/<th class="([^"]+)"/g)].map((x) => x[1]);
    expect(headClasses).toHaveLength(13);
    expect(headClasses.filter((c) => c.includes("num"))).toHaveLength(7);            // #, Page, R, G, B, Predicted, error
    const rowCells = m.match(/<tbody>.*?<\/tr>/s)[0].match(/<td class="/g);
    expect(rowCells).toHaveLength(13);                                                // one cell per heading
  });
  it("shows the Image link as 'Open' on one line", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={[{ ...results[0], image_url: "https://x.example/a.jpg" }]} hasModel />);
    expect(m).toContain('<a href="https://x.example/a.jpg" target="_blank" rel="noreferrer">Open</a>');
  });
  it("puts the download buttons after the table, at the bottom of the panel", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={results} hasModel />);
    expect(m.indexOf("</table>")).toBeLessThan(m.indexOf('class="downloads"'));
    expect(html(<ResultsCard jobId="j" job={{ status: "processing", processed: 1, total: 2 }} results={results} hasModel />)).not.toContain("Download CSV");
  });
  it("keeps the CSV and XLSX download buttons", () => {
    const m = html(<ResultsCard jobId="job1" job={job} results={results} hasModel />);
    expect(m).toContain("Download CSV");
    expect(m).toContain("Download XLSX");
    expect(m).toContain("/api/jobs/job1/download?format=csv");
  });
});
