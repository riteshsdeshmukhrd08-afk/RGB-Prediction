// Small inline SVG icons (decorative: hidden from screen readers).
const base = { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8,
  strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": "true", focusable: "false" };

export const UploadIcon = (p) => (
  <svg {...base} width={32} height={32} {...p}><path d="M12 16V4" /><path d="m7 9 5-5 5 5" /><path d="M20 16v3a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-3" /></svg>
);
export const DownloadIcon = (p) => (
  <svg {...base} {...p}><path d="M12 4v12" /><path d="m7 11 5 5 5-5" /><path d="M20 16v3a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-3" /></svg>
);
export const TableIcon = (p) => (
  <svg {...base} width={40} height={40} {...p}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 10h18M9 4v16" /></svg>
);
export const CheckIcon = (p) => (
  <svg {...base} width={14} height={14} strokeWidth={2.4} {...p}><path d="m5 12 5 5 9-10" /></svg>
);
export const CloseIcon = (p) => (
  <svg {...base} width={14} height={14} strokeWidth={2.2} {...p}><path d="M6 6l12 12M18 6 6 18" /></svg>
);
