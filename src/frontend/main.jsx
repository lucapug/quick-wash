import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// The shell mounts on the seam: `GET /api/views/<screen>` is the read it renders, and the four actions the
// customer has are the seam's own paths. No copy lives here — `src/views.py` is the only place the strings
// are written, so the page a test reads and the page the browser shows are built from one table.
createRoot(document.getElementById("screen")).render(<App />);
