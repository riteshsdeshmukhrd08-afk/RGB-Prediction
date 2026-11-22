import { describe, expect, it } from "vitest";
import { renderToStaticMarkup as html } from "react-dom/server";
import ResultsCard from "./components/ResultsCard.jsx";
import TopBar from "./components/TopBar.jsx";
import Banner from "./components/Banner.jsx";
import App from "./App.jsx";
import { csvFromResults } from "./csvExport.js";

const job = { status: "done", processed: 2, total: 2 };
const outside = { file_name: "c.jpg", page: null, status: "outside_range", error: "", R: 230.1, G: 165, B: 9, cod_mg_l: null, flags: "", warning: "R outside", image_url: null };
const results = [
  { file_name: "a.jpg", page: null, status: "ok", error: "", R: 220.02, G: 140, B: 40, cod_mg_l: 233.25, flags: "", warning: "", image_url: null },
  { file_name: "b.pdf", page: 2, status: "failed", error: "no tube", R: null, G: null, B: null, cod_mg_l: null, flags: "failed", warning: "", image_url: null },
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

describe("Banner", () => {
  const ok = { status: "ok", mongo: "ok", cloudinary: "ok", model: "loaded" };
  it("is not shown while the server is healthy and the COD model is loaded", () => {
    expect(html(<Banner health={ok} healthError={null} onRecheck={() => {}} />)).toBe("");
    expect(html(<Banner health={null} healthError={null} onRecheck={() => {}} />)).toBe("");       // still checking
  });
  it("tells the user clearly when the COD model is missing", () => {
    const m = html(<Banner health={{ ...ok, model: "missing" }} healthError={null} onRecheck={() => {}} />);
    expect(m).toContain('role="alert"');
    expect(m).toContain("The COD model is not loaded on the server.");
    expect(m).toContain("no COD is shown");
    expect(m).toContain("Check again");
  });
  it("keeps the database and backend errors first", () => {
    const db = html(<Banner health={{ ...ok, mongo: "error", mongo_error: "timeout", model: "missing" }} healthError={null} onRecheck={() => {}} />);
    expect(db).toContain("Database not reachable");
    expect(db).not.toContain("COD model");
    const down = html(<Banner health={null} healthError={{ message: "The backend is not reachable. Is it running?" }} onRecheck={() => {}} />);
    expect(down).toContain("The backend is not reachable");
  });
});

describe("Train section is gone", () => {
  it("the page has no Train section, upload or messages about training", () => {
    const page = html(<App />);
    for (const text of ["Train the concentration model", "Choose file", "concentration_ppm", "Upload a CSV", "Train</button>", "batch_features"])
      expect(page).not.toContain(text);
    expect(page).toContain("Results");                                   // the rest of the page is still there
    expect(page).toContain("Input");
  });
  it("the frontend source does not call a training endpoint", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const dir = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
    const files = fs.readdirSync(dir, { recursive: true }).filter((f) => /\.(jsx?|css)$/.test(f) && !/\.test\./.test(f));
    expect(files.length).toBeGreaterThan(5);
    for (const f of files) expect(fs.readFileSync(path.join(dir, f), "utf8").toLowerCase(), f).not.toMatch(/api\/train|traincard|trainparts|trainstate|train-card|train-grid|startTraining|getTraining|previewTrainingFile|getCurrentModel|getCurrentReport/i);
  });
});

describe("Results table", () => {
  const heads = (m) => [...m.matchAll(/<th class="[^"]*">([^<]*)<\/th>/g)].map((x) => x[1]);
  it("has exactly the requested columns in order", () => {
    expect(heads(html(<ResultsCard jobId="j" job={job} results={results} />))).toEqual(["File", "R", "G", "B", "COD (mg/L)", "Status"]);
  });
  it("does not have the removed columns or the flagged count", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={[results[0], outside, results[1]]} />);
    for (const gone of ["± error", "Flags", "Notes", "Predicted concentration", "flagged", "Colour", "Image", "swatch", 'class="tag"', "ppm)"]) expect(m).not.toContain(gone);
    expect(m).not.toContain("R outside");                                   // the warning text is not shown any more
  });
  it("shows R, G, B and the COD in mg/L", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={results} />);
    expect(m).toMatch(/<td class="c-rgb num">220\.02<\/td><td class="c-rgb num">140\.00<\/td><td class="c-rgb num">40\.00<\/td><td class="c-cod num">233\.3<\/td>/);
  });
  it("shows the text 'outside range' instead of a number, and keeps the measured R, G, B", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={[outside]} />);
    expect(m).toMatch(/<td class="c-cod num">outside range<\/td>/);
    expect(m).toContain('<span class="pill warn">outside range</span>');
    expect(m).toContain(">230.10<");
  });
  it("shows status OK, outside range or Failed, with dashes for a failed photo", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={[results[0], outside, results[1]]} />);
    expect(m).toContain('<span class="pill ok">OK</span>');
    expect(m).toContain('<span class="pill warn">outside range</span>');
    expect(m).toContain('<span class="pill bad">Failed</span>');
    expect(m).toMatch(/<td class="c-rgb num">–<\/td><td class="c-rgb num">–<\/td><td class="c-rgb num">–<\/td><td class="c-cod num">–<\/td>/);
  });
  it("names the page of a PDF page next to the file", () => {
    expect(html(<ResultsCard jobId="j" job={job} results={[results[1]]} />)).toContain("b.pdf (p. 2)");
  });
  it("keeps 'failed' and the status in the summary row, without a flagged count", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={results} />);
    const row = m.match(/<div class="summary">.*?<\/div>/s)[0];
    expect(row).toContain('<span class="pill ok">done</span>');
    expect(row).toContain('<span class="figure"><b class="mono">2</b><span>rows</span></span>');
    expect(row).toContain('<span class="figure"><b class="mono">1</b><span>failed</span></span>');
    expect(row).not.toContain("flagged");
    expect(row.indexOf("pill")).toBeLessThan(row.indexOf("rows"));
  });
  it("uses a fixed layout with a class on every column, so it fits the panel", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={results} />);
    const headClasses = [...m.matchAll(/<th class="([^"]+)"/g)].map((x) => x[1]);
    expect(headClasses).toEqual(["c-file", "c-rgb num", "c-rgb num", "c-rgb num", "c-cod num", "c-status"]);
    expect(m.match(/<tbody>.*?<\/tr>/s)[0].match(/<td class="/g)).toHaveLength(6);
  });
  it("uses the singular for exactly one row", () => {
    const one = html(<ResultsCard jobId="j" job={job} results={[results[0]]} />);
    expect(one).toContain('<b class="mono">1</b><span>row</span>');
    expect(html(<ResultsCard jobId="j" job={job} results={[]} />)).toContain('<b class="mono">0</b><span>rows</span>');
  });
  it("colours the pill by state: done green, processing amber, failed red", () => {
    const pill = (status) => html(<ResultsCard jobId="j" job={{ status, processed: 3, total: 15 }} results={results} />).match(/<span class="(pill [a-z]+)">([a-z]+)<\/span>/)[0];
    expect(pill("done")).toBe('<span class="pill ok">done</span>');
    expect(pill("processing")).toBe('<span class="pill warn">processing</span>');
    expect(pill("failed")).toBe('<span class="pill bad">failed</span>');
  });
  it("shows the progress count in the row while processing", () => {
    expect(html(<ResultsCard jobId="j" job={{ status: "processing", processed: 3, total: 15 }} results={results} />)).toContain("3/15 processed");
    expect(html(<ResultsCard jobId="j" job={job} results={results} />)).not.toContain("processed");
  });
  it("shows a centred empty state before any job", () => {
    const m = html(<ResultsCard jobId={null} job={null} results={[]} />);
    expect(m).toContain('class="empty"');
    expect(m).toContain("Results appear here after you press Run.");
  });
  it("puts the download buttons after the table, at the bottom of the panel", () => {
    const m = html(<ResultsCard jobId="j" job={job} results={results} />);
    expect(m.indexOf("</table>")).toBeLessThan(m.indexOf('class="downloads"'));
    expect(html(<ResultsCard jobId="j" job={{ status: "processing", processed: 1, total: 2 }} results={results} />)).not.toContain("Download CSV");
  });
  it("keeps the CSV and XLSX download buttons", () => {
    const m = html(<ResultsCard jobId="job1" job={job} results={results} />);
    expect(m).toContain("Download CSV");
    expect(m).toContain("Download XLSX");
    expect(m).toContain("/api/jobs/job1/download?format=csv");
  });
  it("the combined CSV has a cod_mg_L column like the server export", () => {
    const lines = csvFromResults([results[0], outside]).trim().split("\n");
    expect(lines[0]).toBe("file_name,page,status,R,G,B,cod_mg_L,flags,warning,error,image_url");
    expect(lines[1]).toBe("a.jpg,,ok,220.02,140,40,233.25,,,,");
    expect(lines[2]).toBe("c.jpg,,outside_range,230.1,165,9,,,R outside,,");
  });
});
