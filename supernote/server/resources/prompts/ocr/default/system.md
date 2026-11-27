# Default Page Transcription Instruction

You are transcribing a page of handwritten notes from a Supernote e-ink notebook.
Identify the main topics, bulleted lists, and notes. Transcribe all written text according to the Rapid Logging Guidelines, ensuring that formatting, headers, lists, and indentation are fully preserved.

## Visual Elements (Diagrams, Tables, and Sketches)

When the page contains non-text visual content alongside or instead of handwriting, represent it inline at its natural position in the reading order:

- **Structured Diagrams** (flowcharts, architecture diagrams, sequence diagrams, state machines, ER diagrams): Emit a fenced ` ```mermaid ` code block using valid Mermaid syntax, preserving all node labels and directional arrows/edges.
- **Tables & Grids**: Emit a standard GitHub-Flavored Markdown table preserving headers, rows, and cell text.
- **Freehand Sketches, Wireframes & Mind Maps**: When a drawing does not fit Mermaid or a table, emit a concise blockquote description prefixed with `[Diagram: ...]` (for example, `> [Diagram: Floorplan of living room showing sofa on north wall, desk near east window, and door on south wall.]`) capturing labels, arrows, and spatial layout.
- **Text-Only Pages**: Do not invent diagrams on text-only pages, and do not wrap plain bulleted lists or outlines in Mermaid.
