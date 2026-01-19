# Supernote Web Viewer - Architecture & Design Proposal

This document outlines the recommended architecture for building an open-source web viewer for Supernote files. The goal is to replace the legacy, proprietary Vue 2 frontend with a modern, maintainable, and clean codebase that interfaces with a Python backend.

## 1. Architectural Overview

The system consists of two main components:
1.  **Backend (Python):** Handles file system operations, acts as the API, and performs the heavy lifting of converting `.note` files to simpler formats (PDF/PNG) using tools like `supernote-tool`.
2.  **Frontend (Vue 3 SPA):** A lightweight "dumb" client that requests file lists and displays them. It delegates rendering logic to the backend.

### Deployment Strategy
To simplify deployment (and avoid CORS issues), the Vue app should be built into static files (`html`, `css`, `js`) and served directly by the Python backend.

```text
[Browser]  <-- HTTP -->  [Python Backend]  <-- File System -->  [Supernote Data]
    |                           |
    |                           +-- Serve API (/api/*)
    |                           +-- Serve Static Assets (index.html, assets/*)
    |
    v
[Vue App] (Running in browser)
```

## 2. Technology Stack

We recommend a modern "Vite" stack to avoid the complexity and bloat of the legacy Webpack/Vue 2 setup.

| Component | Choice | Reason |
| :--- | :--- | :--- |
| **Build Tool** | **Vite** | Extremely fast build times, native ES modules, zero-config for simple setups. |
| **Framework** | **Vue 3** | Uses the **Composition API** (`<script setup>`) for cleaner, reusable logic hooks (composables) instead of "Options API" spaghetti. |
| **Language** | **TypeScript** | Crucial for defining the data contracts (`.note` file structure) to prevent runtime errors. |
| **Styling** | **Tailwind CSS** | rapid UI development; avoids the overhead of component libraries like ElementUI when you just need a simple file grid. |
| **Icons** | **Heroicons** | Simple, clean SVG icons that integrate well with Tailwind. |

## 3. Project Structure

Recommended folder structure for the new repository:

```text
my-supernote-viewer/
├── backend/                  # Your Python Backend
│   ├── app.py                # Entry point (FastAPI/Flask)
│   ├── services/             # Logic for interfacing with supernote-tool
│   └── static/               # (Generated) Where frontend build artifacts go
├── web/                      # The New Frontend Source
│   ├── index.html
│   ├── vite.config.ts        # Vite config (proxies /api to backend in dev)
│   ├── tailwind.config.js
│   └── src/
│       ├── App.vue
│       ├── main.ts
│       ├── api/              # API Client Layer
│       │   └── client.ts     # Axios or Fetch wrapper
│       ├── components/       # Presentational Components
│       │   ├── FileGrid.vue
│       │   ├── FileRow.vue
│       │   └── Breadcrumbs.vue
│       ├── composables/      # Business Logic (The "Brains")
│       │   ├── useFileSystem.ts
│       │   └── useFileViewer.ts
│       ├── types/            # TypeScript Interfaces
│       │   └── file.ts
│       └── views/
│           └── FileBrowser.vue
└── README.md
```

## 4. Implementation Details

### A. Data Contracts (`src/types/file.ts`)

Define the shape of your data upfront. This serves as the contract between your Python backend and the Vue frontend.

```typescript
export interface SupernoteFile {
  id: string;          // Unique identifier or path
  name: string;        // Display name (e.g., "Meeting Notes.note")
  isDirectory: boolean;
  size: number;        // In bytes
  updatedAt: string;   // ISO date string
  extension: 'note' | 'pdf' | 'epub' | null;
}
```

### B. The "Composable" Pattern

Avoid putting logic inside components. Use Composables to manage state.

**`src/composables/useFileSystem.ts`**
*Manages the current directory state and fetching files.*

```typescript
import { ref } from 'vue';
import { fetchFiles } from '../api/client';
import type { SupernoteFile } from '../types/file';

export function useFileSystem() {
  const files = ref<SupernoteFile[]>([]);
  const currentPath = ref('/');
  const isLoading = ref(false);
  const error = ref<string | null>(null);

  async function loadDirectory(path: string) {
    isLoading.value = true;
    error.value = null;
    try {
      files.value = await fetchFiles(path); // Call to Python API
      currentPath.value = path;
    } catch (e) {
      error.value = "Failed to load directory";
    } finally {
      isLoading.value = false;
    }
  }

  return { files, currentPath, isLoading, error, loadDirectory };
}
```

**`src/composables/useFileViewer.ts`**
*Manages the "View" action. This logic replaces the complex "QTServer" flow.*

```typescript
import { convertNoteUrl } from '../api/client';

export function useFileViewer() {
  async function openFile(file: SupernoteFile) {
    // 1. If it's a folder, ignore (handled by navigation)
    if (file.isDirectory) return;

    // 2. If it is already a web-friendly format, open directly
    if (['pdf', 'png', 'jpg'].includes(file.extension)) {
       window.open(`/api/files/download?path=${file.id}`, '_blank');
       return;
    }

    // 3. If it is a .note file, request a conversion first
    if (file.extension === 'note') {
      try {
        // Python backend converts .note -> JSON map or temporary PDF
        const response = await convertNoteUrl(file.id);
        // Open the generated/static URL
        window.open(response.viewUrl, '_blank');
      } catch (e) {
        console.error("Conversion failed", e);
      }
    }
  }

  return { openFile };
}
```

### C. Development vs Production Configuration

**Development (`vite.config.ts`):**
Use the proxy feature to forward API requests to your running Python server so you don't need CORS or running builds.

```typescript
export default defineConfig({
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000', // Your Python Backend Port
        changeOrigin: true,
      }
    }
  }
})
```

**Production (Python):**
Serve the `dist/` folder generated by `npm run build`.

*Example (FastAPI):*
```python
from fastapi.staticfiles import StaticFiles

# Mount assets (JS/CSS)
app.mount("/assets", StaticFiles(directory="web/dist/assets"), name="assets")

# Catch-all route for SPA (Standard Pattern)
@app.get("/{full_path:path}")
async def serve_app(full_path: str):
    # Retrieve file if it exists in dist, otherwise serve index.html
    return FileResponse("web/dist/index.html")
```

## 5. Migration Checklist
When you are ready to start the new repo:
1.  Initialize backend with your Python `supernote-tool` logic.
2.  Initialize frontend with `npm create vite@latest web -- --template vue-ts`.
3.  Install Tailwind (follow their Vite guide).
4.  Copy the types and composables structure from above.
5.  Build the API endpoint `/api/list?path=...` in Python to match the `SupernoteFile` interface.
