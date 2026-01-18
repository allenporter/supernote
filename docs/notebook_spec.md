# Supernote Notebook Format Specification

This document describes the binary format of Supernote `.note` files and provides guidelines for building processing systems (e.g., Knowledge Bases, Indexers) that consume them.

## File Structure Overview

A `.note` file is a binary file composed of a **Header**, a sequence of **Metadata Blocks** and **Data Blocks**, and a **Footer**.

The file structure relies heavily on a "Footer-first" parsing strategy:
1.  **Signature**: The file starts with a signature (magic bytes).
2.  **Tail**: The last 4 bytes of the file contain the absolute byte offset of the **Footer Block**.
3.  **Footer**: Contains global metadata and references (offsets) to all other essential blocks (Pages, Titles, Keywords, etc.).

```text
+-----------------------+ 0x00
| Signature             |
+-----------------------+
| Header Block          |
+-----------------------+
| ... Data Blocks ...   |
| (Layers, Bitmaps)     |
+-----------------------+
| ... Metadata Blocks...|
| (Pages, Links, etc.)  |
+-----------------------+
| Footer Block          |
+-----------------------+ <--- Tail points here
| Tail (4 bytes)        |
+-----------------------+ EOF
```

### Signature
The file begins with a versioned string, e.g., `SN_FILE_VER_20230015`.
- **Legacy**: `SN_FILE_ASA_...` (offset 0)
- **X-Series**: `SN_FILE_VER_...` (offset 4, preceded by 4 bytes of file type info)

## Metadata Blocks

All metadata blocks (Header, Footer, Page Info) follow a Tag-Length-Value-like structure but store data as a sequence of Key-Value pairs wrapped in brackets.

**Format**: `<KEY:VALUE>`

Example:
```text
<FILE_TYPE:NOTE><PAGE:1><DEVICE_DPI:0>
```

**Parsing Rules**:
- Blocks are length-prefixed (4 bytes, little-endian).
- Content is a string of bracketed pairs.
- Duplicate keys (e.g., multiple `LAYERBITMAP` entries) are aggregated into lists.

## Core Components

### Header
Pointed to by the Footer's `FILE_FEATURE` key. Contains file-level attributes:
- `FILE_ID`: Unique identifier for the file (Critical for identity).
- `FILE_RECOGN_TYPE`: Indicates if real-time text recognition is enabled (`1`).

**Example**:
```text
<APPLY_EQUIPMENT:N6><FILE_TYPE:NOTE><FILE_ID:F20231207221454><FILE_RECOGN_TYPE:1>
```

### Pages
The Footer contains a `PAGE` key with a list of offsets to **Page Blocks**.
Each **Page Block** describes the state of a single page:
- `PAGEID`: Unique identifier for the page.
- `RECOGNSTATUS`: Status of handwriting recognition (0=None, 1=Done, 2=Running).
- `RECOGNTEXT`: Offset to the binary block containing recognized text.
- `LAYERS`: List of offsets to **Layer Blocks**.

**Example**:
```text
<PAGEID:P202312072214540><RECOGNSTATUS:0><LAYERS:330><LAYERS:6798>
```

### Layers
A page consists of multiple layers, typically:
- `BGLAYER`: Background template.
- `MAINLAYER`: The primary handwriting layer.
- `LAYER[1-3]`: Additional layers.

Each **Layer Block** defines:
- `LAYERBITMAP`: Offset to the compressed bitmap data.
- `LAYERPROTOCOL`: Compression algorithm used (e.g., `RATTA_RLE`, `SN_ASA_COMPRESS`).

**Example**:
```text
<LAYERNAME:BGLAYER><LAYERPROTOCOL:SN_ASA_COMPRESS><LAYERBITMAP:330>
```

## Binary Protocols

Handwriting data is stored as bitmaps compressed with specific protocols.

### RATTA_RLE / RATTA_RLE_X2
Run-Length Encoding optimized for e-ink handwriting.
- Encodes color indices and run lengths.
- **Colors**: Maps byte values to predefined colors (Black, White, Gray, Dark Gray).
- **Control bytes**:
    - `0xFF`: Special marker for long runs (e.g., blank lines).
    - High-bit set bytes indicate encoded runs vs. literal sequences.

### SN_ASA_COMPRESS
Zlib-compressed bitmap data.
- Used in older files or specific contexts.
- Decompresses to a raw bitmap of `uint16` color codes.

## Encoding & Creation (Inverse Protocols)

To programmatically create valid `.note` files (e.g., generating calendars or reports), you must implement the *encoder* logic, which reverses the read steps defined in `decoder.py`.

### 1. SN_ASA_COMPRESS (Zlib) Encoder
Typically used for **BGLAYER** (Backgrounds).

**Algorithm**:
1.  **Input**: A grayscale image of size `Width=1404`, `Height=1872`.
2.  **Padding**: Append **16 empty rows** to the bottom. New size `(1404, 1888)`.
3.  **Rotation**: Rotate the image **90° Counter-Clockwise**. New size `(1888, 1404)`.
4.  **Formatting**:
    - Flatten the pixels.
    - Convert each pixel to a **Little-Endian 16-bit Key**.
    - **Color Keys**:
        - Black: `0x0000`
        - Dark Gray: `0x2104`
        - Gray: `0xE1E2`
        - White (Transparent): `0xFFFF`
5.  **Compression**: Compress the byte array using **Zlib**.

### 2. RATTA_RLE Encoder
Typically used for **MAINLAYER** (Handwriting) and `LAYER1-3`.

**Structure**:
Stream of `[ColorByte, LengthByte]` pairs.

**Color Mapping**:
- Black: `0x61`
- White/Transparent: `0x62`
- Dark Gray: `0x63`
- Gray: `0x64`
- *Note*: X2 Series adds more colors, but these are sufficient for basic content.

**Length Encoding Logic**:
The `LengthByte` typically encodes `count - 1`.
- **Short Run (1-128)**:
    - Encode `L = count - 1`.
    - Emit `[Color, L]`.
- **Long Loop (Extension)**:
    - If `LengthByte >= 128` (High bit set), it serves as a multiplier for the *next* block of the *same color*.
    - Logic: `TotalLength = 1 + NextL + (((PrevL & 0x7F) + 1) << 7)`
- **Special Marker (0xFF)**:
    - `[Color, 0xFF]` represents a run of **16384** pixels (0x4000).
    - Use this for efficiently clearing large empty areas.

## Deep Dive: Headers & Enums

### Valid Field Values

**`FILE_TYPE`** (Header)
- `NOTE`: Standard notebook file.

**`RECOGNSTATUS`** (Page)
- `0` (None): No recognition performed.
- `1` (Done): Recognition complete. `RECOGNTEXT` block should be present.
- `2` (Running): Recognition is currently in progress (avoid processing).

**`ORIENTATION`** (Page)
- `1000`: Vertical (Portrait).
- `1090`: Horizontal (Landscape).

**`LINKTYPE`** (Link)
- `0`: Page Link (Internal jump).
- `1`: File Link (Jump to another `.note` or `.pdf`).
- `4`: Web Link (URL).

### Layer Structure

A **Page Block** references layers via the `LAYERS` key (list of offsets) or explicit named keys in X-series.

**Standard Layers**:
1.  **`BGLAYER`**: The background template (grid, lines, or custom PNG).
    - Often refers to a shared `STYLE_...` block to save space.
2.  **`MAINLAYER`**: The primary layer where the user writes.
3.  **`LAYER1` - `LAYER3`**: Additional layers for overlaying content.

**Layer Protocol**:
Each layer defines its own compression protocol (`LAYERPROTOCOL`). It is common for `BGLAYER` to use `SN_ASA_COMPRESS` (or just be a raw PNG reference) while `MAINLAYER` uses `RATTA_RLE`.

## Processing System Guidelines

When building systems to index or process Supernote files (e.g., for RAG or Knowledge Bases), follow these guidelines:

### 1. Identity & Stability
- **Files**: Do NOT use the filename as the primary key. Use the `Header.FILE_ID`. This ID persists across renames.
- **Pages**: Use `Page.PAGEID` to address specific pages. Page numbers can change if pages are inserted/deleted, but `PAGEID` stays with the content.

### 2. Change Detection (Incremental Indexing)
- **File Level**: Check the `Footer` metadata or total file size/modtime.
- **Page Level**: Construct a hash of the Page Block metadata (which includes layer pointers and dirty flags).
    - If the Page Block hash changes, the content (handwriting or recognition) has likely changed.
    - Supernote files are append-only for new data but may rewrite metadata blocks. A "hashing module" is essential for efficient re-processing.

### 3. Text Extraction Strategies
You have two paths for extracting text.

> [!IMPORTANT]
> **Architecture Decision**: This project exclusively uses the **Slow Path (OCR)** strategy. We have found that modern LLM-based OCR (e.g., Gemini) provides significantly higher quality transcription than the device's embedded `RECOGNTEXT`. Therefore, we skip parsing the `RECOGNTEXT` block entirely.

**Fast Path (Metadata) [NOT USED]**
- Check `Page.RECOGNTEXT` address.
- If present (>0), read the binary block and decode using `TextDecoder` (Protobuf/JSON based).
- **Pros**: Instant, no heavy compute.
- **Cons**: Only available if the user enabled "Real-time Recognition" and the device has processed it. Quality varies.

**Slow Path (OCR) [SELECTED]**
- If `RECOGNTEXT` is missing, you must render the page.
- decode `LAYERBITMAP` data using the appropriate protocol (`RATTA_RLE`).
- Flatten layers (Background + Main + Layers) into a PNG.
- Pass the PNG to an external OCR engine (e.g., Gemini Flash, Tesseract).
- **Pros**: Works on all files and drawings.
- **Cons**: Expensive, slow.

### 4. Vector vs. Raster
- **Raster**: `LAYERBITMAP` (what you see).
- **Vector**: `TOTALPATH` (available in some versions).
    - `TOTALPATH` contains the raw stylus strokes (x, y, pressure).
    - Useful for high-fidelity SVG generation or analyzing stroke order.
    - **Note**: `parser.py` currently focuses on Raster decoding.

## Specialty Data

- **Keywords**: Defined in Footer (`KEYWORD_...`). Links a specific rectangle on a page to a text label.
- **Links**: Defined in Footer (`LINK...`). Can be internal (jump to page) or external (web/file).

## Unverified Areas / Risks

While the read-path is well understood, the following areas contain uncertainties for *writing* new files:

- **`TOTALPATH` Vector Data**:
    - The `TOTALPATH` block contains vector stroke data (pressure, tilt, etc.).
    - Use Case: High-fidelity SVG export and handwriting recognition.
    - **Risk**: Programmatically generated files usually lack this data (raster only). The device *should* handle missing `TOTALPATH` gracefully (rendering the raster `MAINLAYER`), but this is not fully verified on all firmware versions.
- **`RECOGNTEXT` Generation**:
    - The format of the `RECOGNTEXT` block (protobuf/json hybrid) is complex and not fully documented.
    - **Risk**: You cannot easily "inject" recognized text into a new notebook. Files created programmatically should set `RECOGNSTATUS=0` effectively disabling search/recognition features for that content until the device re-indexes it (if it does).
- **Magic Header Values**:
    - `RATTA_ETMD`: Observed value `0` in A5X/A6X files (X-Series). Likely related to "Electro-Magnetic Touch Device" or model parameters.
    - Fields like this and various DPI settings in the header have opaque values.
    - **Recommendation**: When creating a file, **copy the Header block** from a known-good "Template" file of the same device type (A5X/A6X) rather than synthesising it from scratch.
