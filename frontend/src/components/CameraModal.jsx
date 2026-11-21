import { useEffect, useRef, useState } from "react";

// Opens the camera, and hands back a JPEG File when the user takes a photo.
// Browsers allow the camera only on https:// or http://localhost.
export default function CameraModal({ onCapture, onClose }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("This browser cannot use the camera here (it needs https or localhost).");
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        videoRef.current.srcObject = stream;
        setReady(true);
      } catch (e) {
        setError("Could not open the camera: " + (e.message || e.name));
      }
    }
    start();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop()); // always release the camera
    };
  }, []);

  function snap() {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext("2d").drawImage(v, 0, 0);
    canvas.toBlob(
      (blob) => {
        if (blob) onCapture(new File([blob], `camera-${Date.now()}.jpg`, { type: "image/jpeg" }));
      },
      "image/jpeg",
      0.95,
    );
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Take photo">
      <div className="modal">
        {error ? <p className="error">{error}</p> : <video ref={videoRef} autoPlay playsInline muted />}
        <div className="row">
          <button className="primary" onClick={snap} disabled={!ready}>Take photo</button>
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
