# Supernote Notebook Format Specification

This document specifies the binary framing, metadata block encoding, bitmap compression protocols, and server indexing conventions for Supernote `.note` and `.mark` files.

For the authoritative catalog of all wire `<KEY:VALUE>` tags, enum values, sentinel rules, and Python domain models, see:
- **Wire-format dataclasses & enums**: [`supernote/notebook/schema.py`](../supernote/notebook/schema.py)
- **Loaded domain objects**: [`supernote/notebook/fileformat.py`](../supernote/notebook/fileformat.py)
- **Stream parsers**: [`supernote/notebook/parser.py`](../supernote/notebook/parser.py)
- **Bitmap & text decoders**: [`supernote/notebook/decoder.py`](../supernote/notebook/decoder.py)
- **Notebook reconstruction & merging**: [`supernote/notebook/manipulator.py`](../supernote/notebook/manipulator.py)

---

## File Structure Overview

A Supernote file is an append-friendly binary container read via a **footer-first** parsing strategy:

1. **Prefix & Signature**: Identifies the container family (`note` / `mark`) and format version at byte `0`.
2. **Length-Prefixed Blocks**: Every metadata block and binary payload block (bitmaps, vector paths, keywords, recognition data) is framed as `[uint32_le byte_length][payload]`. An offset of `0` in any metadata tag means the block is absent.
3. **Footer Block**: Directory of byte offsets pointing to the Header (`FILE_FEATURE`), per-page metadata blocks, cover bitmaps, style templates, keywords, titles, and links.
4. **Trailing Sentinel & Footer Pointer**:
   - **X-Series & X2 (`SN_FILE_VER_...`)**: Ends with the 4-byte ASCII literal `"tail"` (`0x74 0x61 0x69 0x6c`) followed by the final 4-byte `uint32_le` absolute byte offset of the Footer Block.
   - **Legacy A5 (`SN_FILE_ASA_...`)**: Ends directly with the 4-byte `uint32_le` absolute byte offset of the Footer Block (no `"tail"` marker and no 4-byte file-type prefix).

```text
X-Series / X2 Container Layout
+------------------------------------------+ 0x00
| File Type ("note" or "mark", 4 bytes)    |
+------------------------------------------+ 0x04
| Format Signature (20 bytes)              |
| e.g. "SN_FILE_VER_20260016"              |
+------------------------------------------+ 0x18 (24)
| Header Block       [uint32 len][<K:V>..] | <--- Footer FILE_FEATURE points here
+------------------------------------------+
| Binary & Metadata Blocks                 |
| - Cover / Style / Layer Bitmaps          |
| - Layer Metadata Blocks                  |
| - Vector Stroke Blocks (TOTALPATH)       |
| - Keyword / Title / Link Blocks          |
| - Page Metadata Blocks                   | <--- Footer PAGE1..N point here
+------------------------------------------+
| Footer Block       [uint32 len][<K:V>..] | <--- Trailing offset points here
+------------------------------------------+ EOF - 8
| Sentinel ("tail", 4 bytes)               |
+------------------------------------------+ EOF - 4
| Footer Offset (uint32_le, 4 bytes)       |
+------------------------------------------+ EOF
```

### Signatures & Device Dimensions

| Generation | Prefix (`0x00`) | Signature | Canvas (`W x H`) | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Original A5** | *(none)* | `SN_FILE_ASA_20190529` | `1404 x 1872` | Single-layer pages (`DATA` + `PROTOCOL`), no `"tail"` sentinel |
| **X-Series (A5 X / A6 X)** | `note` / `mark` | `SN_FILE_VER_20200001` – `20230014` | `1404 x 1872` | 5-layer pages (`MAINLAYER`, `LAYER1..3`, `BGLAYER`) |
| **X2 Nomad (`N6`)** | `note` / `mark` | `SN_FILE_VER_20230015` – `20260016` | `1404 x 1872` | Extended X2 grayscale RLE palette (`>= 20230015`) |
| **X2 Manta (`N5`)** | `note` / `mark` | `SN_FILE_VER_20230015` – `20260016` | `1920 x 2560` | Selected when Header `APPLY_EQUIPMENT` is `N5` |

#### Signature History & Canvas Geometry
- **Signature `SN_FILE_VER_20260016`**: Introduced in Chauvet 3.28.42 (May 2026) and active across all subsequent releases including Chauvet 3.31.45 (Nomad/Manta) and Chauvet 2.28.42 (A5 X / A6 X). Containers written by older firmware (`SN_FILE_VER_20230015` and earlier) are forward-compatible and parsed transparently.
- **Coordinate Systems & Aspect Ratios**:
  - Nomad (`N6`) and legacy X-series (`A5X`, `A6X`) notebooks render to a `1404 x 1872` pixel coordinate plane.
  - Manta (`N5`) notes render to a higher-resolution `1920 x 2560` pixel canvas with an EMR digitizer scaling ratio of `8.45` hardware units per screen pixel.
  - The notebook canvas dimension is determined by `HeaderMetadata.apply_equipment`: parsing engines must query this field to scale vector strokes, template layers, and annotation overlays correctly.

---

## Metadata Block Wire Syntax

All metadata blocks encode UTF-8 sequences of angle-bracketed `<KEY:VALUE>` tags parsed by `extract_parameters()` and serialized by `encode_parameters()` in [`schema.py`](../supernote/notebook/schema.py):

- **Block Framing**: Each block starts with a 4-byte little-endian `uint32` byte length, followed by `byte_length` UTF-8 bytes of `<KEY:VALUE>` pairs.
- **Repeated Keys**: When the same key appears multiple times in one block (for example, multiple keywords sharing a row key in the Footer, or repeated `PAGE` entries in legacy A5 footers), values are preserved in order as a `list[str]`.
- **Sentinels**: Optional string or digest fields commonly use `"none"` or `"0"` on the wire when unset; block pointer fields use `"0"` when no target block is written.
- **Rectangle Coordinates**: Geometry tags (`KEYWORDRECT`, `TITLERECT`, `LINKRECT`, and their `*ORI` counterparts) store comma-separated `left,top,width,height` integers (`Rect` in [`schema.py`](../supernote/notebook/schema.py)).

---

## Core Metadata Blocks

Every block below maps 1:1 to a typed dataclass in [`supernote/notebook/schema.py`](../supernote/notebook/schema.py), which preserves unknown future firmware tags in `.extra` and supports lossless wire round-tripping via `.to_params()` / `.to_wire_dict()`.

### 1. Header Block (`HeaderMetadata`)

Referenced by `FILE_FEATURE` in the Footer. Stores notebook-wide identity, hardware model (`APPLY_EQUIPMENT`), DPI, template defaults, and real-time handwriting recognition settings (`FILE_RECOGN_TYPE=1`).

<!-- schema: HeaderMetadata -->
```text
<FILE_TYPE:NOTE><APPLY_EQUIPMENT:N6><FILE_ID:F202512072214597017338I6OJBpDccy1><FILE_RECOGN_TYPE:0><DEVICE_DPI:0><SOFT_DPI:0><FILE_PARSE_TYPE:0><RATTA_ETMD:0>
```

### 2. Footer Block (`FooterMetadata`)

Located via the final 4-byte offset at EOF. Indexes all top-level blocks using positional and prefix-addressed keys:

- **`FILE_FEATURE`**: Byte offset of the `HeaderMetadata` block.
- **Pages**: `PAGE1`, `PAGE2`, ..., `PAGE<N>` (1-based) in X-series containers; repeated `PAGE` tags in legacy A5 containers.
- **Covers**: `COVER_0` (built-in cover), `COVER_1` (legacy A5 cover), or `COVER_2` (custom X-series cover bitmap).
- **Styles**: `STYLE_<style_name>` (or `STYLE_<style_name><md5>` for custom `user_*` templates, which may appear multiple times in append-updated footers) and optional `PDFSTYLELIST` (offset to comma-separated base64 `user_pdf_*` style names).
- **Keywords**: `KEYWORD_<page4><top4>` — 1-based 4-digit page number + 4-digit zero-padded `KEYWORDRECTORI.top`.
- **Titles**: `TITLE_<page4><top4><left4>` — 1-based 4-digit page number + 8-digit `<top4><left4>` from `TITLERECTORI`.
- **Links**: `LINKO_<page4><top4><left4><height4><width4>` (outgoing) and `LINKI_...` (incoming), using 1-based 4-digit page number + 16-digit `LINKRECT` geometry.

<!-- schema: FooterMetadata -->
```text
<FILE_FEATURE:24><PAGE1:1148><PAGE2:2410><COVER_2:0><STYLE_style_white:312><KEYWORD_00010020:916><TITLE_000100570121:589><LINKO_00010060005000800070:900><DIRTY:0>
```

### 3. Page Block (`PageMetadata`)

Each `PAGE<N>` footer pointer addresses a `PageMetadata` block describing page identity (`PAGEID`), orientation (`ORIENTATION`), background template (`PAGESTYLE` / `PAGESTYLEMD5`), vector strokes (`TOTALPATH`), recognition status/streams (`RECOGNSTATUS`, `RECOGNTEXT`, `RECOGNFILE`), text-box exclusion regions (`PAGETEXTBOX`, `DISABLE`), star marks (`FIVESTAR`), external links (`EXTERNALLINKINFO`), object IDs (`IDTABLE`), and layer slots (`MAINLAYER`, `LAYER1`, `LAYER2`, `LAYER3`, `BGLAYER`):

<!-- schema: PageMetadata -->
```text
<PAGEID:P202512072214597028199Q3d9fcB25s><PAGESTYLE:style_white><PAGESTYLEMD5:0><ORIENTATION:1000><MAINLAYER:612><LAYER1:0><LAYER2:0><LAYER3:0><BGLAYER:840><LAYERINFO:[{"layerId"#0,"name"#"Main layer","isBackgroundLayer"#false,"isAllowAdd"#false,"isCurrentLayer"#true,"isVisible"#true,"isDeleted"#false,"isAllowUp"#false,"isAllowDown"#false}]><LAYERSEQ:MAINLAYER,BGLAYER><TOTALPATH:1020><RECOGNSTATUS:0><RECOGNTEXT:0><RECOGNFILE:0><PAGETEXTBOX:1><DISABLE:120,340,480,160>
```

#### Typed Text Box Metadata Tags
- **`<PAGETEXTBOX:...>`**: Indicates typed text box content exists on the page (typically set to `1` or points to text-box table data).
- **`<DISABLE:...>`**: Formatted as pipe-separated bounding rectangles (`<x>,<y>,<w>,<h>|<x2>,<y2>,<w2>,<h2 >|...`). Defines exclusion bounding boxes where on-device handwriting recognition engines (MyScript) must suppress recognition. This prevents the handwriting parser from attempting to interpret rendered font glyphs as handwritten characters.

#### `LAYERINFO` Encoding Variants
`LAYERINFO` stores a JSON array of per-layer visibility descriptors (`LayerVisibility` in [`schema.py`](../supernote/notebook/schema.py)):
- **Hash-escaped JSON (older Chauvet)**: Replaces JSON `:` separators with `#` so colons do not collide with the `<KEY:VALUE>` parser.
- **Base64 JSON (Chauvet 3.25.39+)**: Base64-encodes the UTF-8 JSON array so user-defined layer names containing `#` or `:` round-trip safely.
- **`none` Sentinel**: Used in `.mark` annotation files, where visibility falls back to showing layers with `LAYERTYPE == "MARK"`.

### 4. Layer Block (`LayerMetadata`)

Each non-zero layer offset on a page (`MAINLAYER`, `LAYER1..3`, `BGLAYER`) points to a `LayerMetadata` block specifying the layer's slot name, compression protocol, and compressed bitmap address (`LAYERBITMAP`):

<!-- schema: LayerMetadata -->
```text
<LAYERTYPE:NOTE><LAYERPROTOCOL:RATTA_RLE><LAYERNAME:MAINLAYER><LAYERPATH:0><LAYERBITMAP:447><LAYERVECTORGRAPH:0><LAYERRECOGN:0>
```

### 5. Keyword, Title & Link Blocks (`KeywordMetadata`, `TitleMetadata`, `LinkMetadata`)

Specialty index entries pointed to by the Footer store bounding-box geometry and payload pointers:

- **Keyword (`KeywordMetadata`)**: Note that `<KEYWORDPAGE>` is **1-based** on the wire (`KeywordMetadata.page_index` normalizes it to 0-based in Python). `KEYWORDSITE` points to the raw UTF-8 keyword string block.

<!-- schema: KeywordMetadata -->
```text
<KEYWORDSEQNO:0><KEYWORDPAGE:1><KEYWORDRECT:10,20,30,40><KEYWORDRECTORI:10,20,30,40><KEYWORDSITE:916><KEYWORDLEN:7><KEYWORD:ks-tilt>
```

- **Title (`TitleMetadata`)**: Heading outline metadata with a rasterized stroke preview bitmap at `TITLEBITMAP`.

<!-- schema: TitleMetadata -->
```text
<TITLESEQNO:0><TITLELEVEL:1><TITLERECT:121,100,341,93><TITLERECTORI:121,57,341,180><TITLEBITMAP:589><TITLEPROTOCOL:RATTA_RLE><TITLESTYLE:1000254>
```

- **Link (`LinkMetadata`)**: Internal page jump (`LINKTYPE=0`), cross-file link (`LINKTYPE=1`), document/PDF link (`LINKTYPE=2`), or web URL (`LINKTYPE=4`, with `LINKFILE` base64-encoded). Firmware writes the indicator compression tag as `<LINKPROTOCAL:...>` (with typeset/digest links also carrying `OBJPAGE`, `FONTSIZE`, `FONTPATH`, `FULLTEXT`, `SHOWTEXT`, `ANTI`, `BOLD`, `ITALIC`).

<!-- schema: LinkMetadata -->
```text
<LINKTYPE:4><LINKINOUT:0><LINKRECT:50,60,70,80><LINKRECTORI:50,60,70,80><LINKTIMESTAMP:12345><LINKFILE:aHR0cHM6Ly9leGFtcGxlLmNvbQ==><LINKFILEID:none><PAGEID:none><OBJPAGE:0><LINKBITMAP:900><LINKPROTOCAL:RATTA_RLE><LINKSTYLE:style_link>
```

---

## Enumerated Wire Values

See [`supernote/notebook/schema.py`](../supernote/notebook/schema.py) for complete enum definitions (`FileType`, `EquipmentType`, `LayerName`, `LayerProtocol`, `LayerType`, `PageOrientation`, `RecognitionStatus`, `LinkType`, `LinkDirection`).

| Wire Tag | Enum Class | Values |
| :--- | :--- | :--- |
| `FILE_TYPE` | `FileType` | `NOTE` (notebook), `MARK` (document annotation sidecar) |
| `APPLY_EQUIPMENT` | `EquipmentType` | `A5`, `A5X`, `A6X`, `N5` (A5 X2 Manta), `N6` (A6 X2 Nomad) |
| `ORIENTATION` | `PageOrientation` | `1000` (vertical), `1090` (horizontal 90°), `1180` (vertical 180°), `1270` (horizontal 270°) |
| `RECOGNSTATUS` | `RecognitionStatus` | `0` (none), `1` (done — `RECOGNTEXT` ready), `2` (running) |
| `LAYERPROTOCOL` / `PROTOCOL` | `LayerProtocol` | `RATTA_RLE`, `SN_ASA_COMPRESS`, `PNG` |
| `LAYERTYPE` | `LayerType` | `NOTE`, `MARK`, `BACKGROUND` |
| `LINKTYPE` | `LinkType` | `0` (page link), `1` (file link), `2` (document link), `4` (web URL) |
| `LINKINOUT` | `LinkDirection` | `0` (outgoing), `1` (incoming) |

---

## Binary Payloads & Compression Protocols

### 1. `RATTA_RLE` & X2 High-Res Grayscale (`RattaRleDecoder` / `RattaRleX2Decoder`)

Used for `MAINLAYER`, `LAYER1..3`, built-in `BGLAYER` styles on modern firmware, and title/link bitmaps. Encodes a stream of `[color_code, length_byte]` byte pairs in [`decoder.py`](../supernote/notebook/decoder.py):

- **Color Codes (`RattaRleDecoder`)**:
  - `0x61`: Black
  - `0x62`: Background / Transparent
  - `0x63`: Dark Gray (`0x9D` on X2 `SN_FILE_VER_20230015+`; `0x63` retained for compatibility)
  - `0x64`: Gray (`0xC9` on X2 `SN_FILE_VER_20230015+`; `0x64` retained for compatibility)
  - `0x65`: White
  - `0x66`: Marker Black
  - `0x67`: Marker Dark Gray (`0x9E` on X2)
  - `0x68`: Marker Gray (`0xCA` on X2)
  - On X2 notebooks (`signature >= SN_FILE_VER_20230015`), unmapped byte codes represent literal 8-bit grayscale intensities.
- **Run-Length Rules**:
  - **Short run (`length_byte < 0x80`)**: Emits `length_byte + 1` pixels (`1..128`).
  - **Special blank marker (`length_byte == 0xFF`)**: Emits `16384` (`0x4000`) pixels (`1024` when `all_blank` hint applies).
  - **Extended run (`length_byte & 0x80 != 0`, `!= 0xFF`)**: Holds `(prev_color, prev_len)`. If the next pair has the same `color_code`, emits `1 + next_len + (((prev_len & 0x7F) + 1) << 7)` pixels; otherwise flushes `((prev_len & 0x7F) + 1) << 7` pixels of `prev_color` first. At EOF, any held run is bit-shifted via `_adjust_tail_length` to fill the remaining scanline gap.

### 2. `SN_ASA_COMPRESS` (`FlateDecoder`)

Zlib-compressed `uint16_le` bitmap used on legacy A5 pages and older backgrounds:
1. Decompresses via `zlib` to `1404 * 1888 * 2` bytes (`uint16_le`).
2. Reshapes to `(1404, 1888)`, rotates 90° clockwise, and trims the bottom 16 padding rows to yield `(1404, 1872)`.
3. Maps `uint16` color keys: `0x0000` (Black), `0x2104` (Dark Gray), `0xE1E2` (Gray), `0xFFFF` (White/Background).

### 3. Background PNGs (`PngDecoder`)

When a page uses a custom (`user_*`) or InkHub/plugin PNG template, `BGLAYER`'s `LAYERBITMAP` block stores raw PNG bytes (`\x89PNG\r\n\x1a\n...`) matching the page canvas dimensions (`(width, height)` in portrait or `(height, width)` in landscape), decoded directly via Pillow (`PngDecoder`). Firmware may record `<LAYERPROTOCOL:PNG>`, `<LAYERPROTOCOL:RATTA_RLE>`, or omit `<LAYERPROTOCOL>` on PNG `BGLAYER` blocks, and occasionally stamps `<LAYERPROTOCOL:PNG>` onto foreground `MAINLAYER` blocks whose `LAYERBITMAP` remains `RATTA_RLE`; `Layer.bitmap_protocol` resolves the effective codec from the PNG file signature and layer slot.

### 4. Embedded Recognition Text (`TextDecoder`)

When `FILE_RECOGN_TYPE == 1` and `RECOGNSTATUS == 1`, `RECOGNTEXT` points to a length-prefixed block containing **base64-encoded UTF-8 JSON** (`{"elements": [{"type": "Text", "label": "...", "words": [{"bounding-box": {"y": ...}}]}]}`), decoded and spatially ordered by `TextDecoder` in [`decoder.py`](../supernote/notebook/decoder.py).

### 5. Vector Strokes, Text Boxes & Dynamic Content (`TOTALPATH`)

The `TOTALPATH` block stores the structured, stroke-level vector representation of page content. While flattened layers (`MAINLAYER` etc.) store raster bitmaps for fast display, `TOTALPATH` enables stroke-level erasing, lasso transformations, handwriting recognition, and text editing on the physical device.

#### Triple-Representation Model for Text Boxes
Supernote firmware manages typed text boxes through a synchronized three-part representation:
1. **Visual Raster Layer**: Rendered font glyphs are rasterized directly into the foreground layer (`MAINLAYER`) using standard `RATTA_RLE` encoding.
2. **Page Recognition Filtering**: The `PageMetadata` block sets `<PAGETEXTBOX:1>` and records `<DISABLE:left,top,width,height|...>` covering the bounding box of each text box. This instructs the on-device MyScript handwriting recognition engine (`RECOGNTEXT` / `RECOGNFILE`) to ignore these rectangular screen regions, preventing typed font text from corrupting handwriting recognition streams.
3. **Editable Object Record**: `TOTALPATH` stores a dedicated record with attributes:
   - `pen = 0`
   - `predictName = "0000"`
   - `m_copy = 30`
   - A 19-field comma-separated base64 metadata payload (`sized_str_1`), where field index 12 stores the raw UTF-8 string content. This allows on-device keyboard re-editing, cursor placement, and font re-rendering.

#### Pen Types & Contour Representation (`PointContour`)
Chauvet firmware additions include:
- **Calligraphy Pen (`penType=15`)**: Variable-angle, pressure-sensitive chiseled stroke dynamics.
- **Ink Pen (`penType=16`)**: Fountain pen flow dynamics.
- **Transformed & Dynamic Elements**: When content is flipped (horizontal/vertical flip introduced in Chauvet 3.31.45), non-proportionally scaled, or stamped from stickers/plugins, the device:
  - Rasterizes the visual result directly into `MAINLAYER` (`RATTA_RLE`).
  - Encodes vector boundary rings directly in the `PointContour` subsection of `TOTALPATH` in page-pixel coordinates.

#### Plugin Elements (`sn-plugin-lib 0.2.3`)
Third-party InkHub plugins interact with `TOTALPATH` via standardized `Element` structures:
- `0`: Standard handwriting stroke
- `100`: Title / Heading
- `200`: Picture / Sticker
- `500`–`502`: Text box / Digest
- `600`: Link indicator
- `700`: Geometric primitives (`straightLine`, `GEO_circle`, `GEO_ellipse`, `GEO_polygon`)
- `800`: Five-star mark

Beginning with `sn-plugin-lib 0.2.3`, plugin coordinates are expressed directly in Android screen pixels rather than requiring hardware EMR digitizer conversions.

---

## Companion Sync Formats (`.snplg` & `.snstk`)

Supernote devices and Private Cloud synchronize companion zip archives alongside `.note` files:

1. **InkHub Plugin Bundles (`.snplg`)**:
   - Standard ZIP archive containing:
     - `PluginConfig.json`: Manifest declaring plugin identity, version, permissions, UI capabilities, and lifecycle hooks.
     - React Native JavaScript bundle providing the interactive frontend running on the device.
     - Optional native Android APK/NPK binary extensions (`app.npk`).
   - Synced to device plugin directories and managed via InkHub. Coordinates emitted onto pages adhere to the page-pixel standard established in `sn-plugin-lib 0.2.3`.

2. **Sticker Packs (`.snstk`)**:
   - Standard ZIP archive containing collections of `<name>.sticker` definitions, raster assets, and thumbnail previews.
   - Registered in Ratta Private Cloud / MariaDB reference schema under file type serial `42` (`snbak` backup archives use serial `41`).
   - Once inserted onto a page, sticker instances follow the dynamic content model (rasterized into `MAINLAYER`, bounding box contours recorded in `PointContour`).

---

## Processing System Guidelines

When building indexing, search, or sync pipelines (such as the server modules in [`page_hashing.py`](../supernote/server/services/processor_modules/page_hashing.py)):

1. **Stable Identity**:
   - **Notebook Level**: Key by `HeaderMetadata.file_id` (`Notebook.file_id`) rather than file path so renames and moves preserve history.
   - **Page Level**: Key by `PageMetadata.page_id` (`Page.page_id`) rather than 0-based page index so page insertions, deletions, and reordering do not orphan cached artifacts.
2. **Deterministic Page Change Detection**:
   - [`PageHashingModule`](../supernote/server/services/processor_modules/page_hashing.py) hashes the wire-serialized `PageMetadata` (`page.to_wire_dict()`, stripping volatile recognition keys) together with each referenced binary block (`LAYERBITMAP`, `DATA`, `TOTALPATH`).
   - Do **not** alter `PageMetadata.to_wire_dict()` key ordering or value formatting without migrating stored `NotePageContentDO.content_hash` digests, or existing deployments will unnecessarily re-render and re-OCR unchanged pages.
3. **Text Extraction Strategy**:
   - **Rendered Vision OCR vs. `RECOGNTEXT`**: While `RECOGNTEXT` provides fast access to recognized handwriting on real-time recognition notebooks (`FILE_RECOGN_TYPE == 1`), it has two critical limitations:
     1. It is entirely absent (`RECOGNSTATUS == 0`) on Standard (non-real-time) notebooks.
     2. On-device handwriting recognition explicitly masks out regions defined in `<DISABLE:...>` bounding boxes. Consequently, typed text boxes (`PAGETEXTBOX`) and embedded plugin texts are **omitted** from `RECOGNTEXT` on-device.
   - **Architecture Decision**: The Supernote server pipeline uses the **Rendered Vision OCR** path (rendering layered pages to PNG and transcribing via vision LLMs) rather than relying solely on device-generated `RECOGNTEXT`. This ensures consistent, comprehensive transcription across Standard notebooks, typed text boxes, diagram labels, and mixed handwriting.

---

## Writing & Reconstruction Caveats

[`reconstruct()` and `merge()`](../supernote/notebook/manipulator.py) rebuild valid latest-signature (`SN_FILE_VER_20260016`) `.note` streams and validate the result through `SupernoteXParser.parse_stream()`. Keep the following device constraints in mind when synthesizing notebooks programmatically:

- **`TOTALPATH` Vector Strokes**: Supernote firmware uses `TOTALPATH` for stroke-level erasing, lasso selection, and on-device re-recognition. Raster-only generated pages (`TOTALPATH=0`) display as bitmaps on `MAINLAYER` / `BGLAYER` but strokes are not individually editable on the device.
- **Opaque Header Parameters**: Hardware calibration tags such as `RATTA_ETMD`, `IS_OLD_APPLY_EQUIPMENT`, and `ANTIALIASING_CONVERT` carry device-specific values; prefer cloning `HeaderMetadata` from a template notebook matching the target `EquipmentType` rather than inventing values from scratch.
