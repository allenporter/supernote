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
| e.g. "SN_FILE_VER_20230015"              |
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
| **X-Series (A5 X / A6 X)** | `note` / `mark` | `SN_FILE_VER_20200001` – `20210010` | `1404 x 1872` | 5-layer pages (`MAINLAYER`, `LAYER1..3`, `BGLAYER`) |
| **X2 Nomad (`N6`)** | `note` / `mark` | `SN_FILE_VER_20230015` | `1404 x 1872` | Extended X2 grayscale RLE palette (`>= 20230015`) |
| **X2 Manta (`N5`)** | `note` / `mark` | `SN_FILE_VER_20230015` | `1920 x 2560` | Selected when Header `APPLY_EQUIPMENT` is `N5` |

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
- **Styles**: `STYLE_<style_name>` (or `STYLE_<style_name><md5>` for custom `user_*` templates).
- **Keywords**: `KEYWORD_<page4><top4>` — 1-based 4-digit page number + 4-digit zero-padded `KEYWORDRECTORI.top`.
- **Titles**: `TITLE_<page4><top4><left4>` — 1-based 4-digit page number + 8-digit `<top4><left4>` from `TITLERECTORI`.
- **Links**: `LINKO_<page4><top4><left4><height4><width4>` (outgoing) and `LINKI_...` (incoming), using 1-based 4-digit page number + 16-digit `LINKRECT` geometry.

<!-- schema: FooterMetadata -->
```text
<FILE_FEATURE:24><PAGE1:1148><PAGE2:2410><COVER_2:0><STYLE_style_white:312><KEYWORD_00010020:916><TITLE_000100570121:589><LINKO_00010060005000800070:900><DIRTY:0>
```

### 3. Page Block (`PageMetadata`)

Each `PAGE<N>` footer pointer addresses a `PageMetadata` block describing page identity (`PAGEID`), orientation (`ORIENTATION`), background template (`PAGESTYLE` / `PAGESTYLEMD5`), vector strokes (`TOTALPATH`), recognition status/streams (`RECOGNSTATUS`, `RECOGNTEXT`, `RECOGNFILE`), and layer slots (`MAINLAYER`, `LAYER1`, `LAYER2`, `LAYER3`, `BGLAYER`):

<!-- schema: PageMetadata -->
```text
<PAGEID:P202512072214597028199Q3d9fcB25s><PAGESTYLE:style_white><PAGESTYLEMD5:0><ORIENTATION:1000><MAINLAYER:612><LAYER1:0><LAYER2:0><LAYER3:0><BGLAYER:840><LAYERINFO:[{"layerId"#0,"name"#"Main layer","isBackgroundLayer"#false,"isAllowAdd"#false,"isCurrentLayer"#true,"isVisible"#true,"isDeleted"#false,"isAllowUp"#false,"isAllowDown"#false}]><LAYERSEQ:MAINLAYER,BGLAYER><TOTALPATH:1020><RECOGNSTATUS:0><RECOGNTEXT:0><RECOGNFILE:0>
```

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

- **Link (`LinkMetadata`)**: Internal page jump (`LINKTYPE=0`), cross-file link (`LINKTYPE=1`), or web URL (`LINKTYPE=4`, with `LINKFILE` base64-encoded).

<!-- schema: LinkMetadata -->
```text
<LINKTYPE:4><LINKINOUT:0><LINKRECT:50,60,70,80><LINKRECTORI:50,60,70,80><LINKTIMESTAMP:12345><LINKFILE:aHR0cHM6Ly9leGFtcGxlLmNvbQ==><LINKFILEID:none><PAGEID:none><LINKBITMAP:900><LINKPROTO:RATTA_RLE><LINKSTYLE:style_link>
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
| `LAYERPROTOCOL` / `PROTOCOL` | `LayerProtocol` | `RATTA_RLE`, `SN_ASA_COMPRESS` |
| `LAYERTYPE` | `LayerType` | `NOTE`, `MARK`, `BACKGROUND` |
| `LINKTYPE` | `LinkType` | `0` (page link), `1` (file link), `4` (web URL) |
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

### 3. Custom Background PNGs (`PngDecoder`)

When a page uses a custom template (`PAGESTYLE` starting with `user_`), `BGLAYER`'s `LAYERBITMAP` block stores raw PNG bytes matching the notebook's `(width, height)` canvas, decoded directly via Pillow (`PngDecoder`).

### 4. Embedded Recognition Text (`TextDecoder`)

When `FILE_RECOGN_TYPE == 1` and `RECOGNSTATUS == 1`, `RECOGNTEXT` points to a length-prefixed block containing **base64-encoded UTF-8 JSON** (`{"elements": [{"type": "Text", "label": "...", "words": [{"bounding-box": {"y": ...}}]}]}`), decoded and spatially ordered by `TextDecoder` in [`decoder.py`](../supernote/notebook/decoder.py).

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

> [!IMPORTANT]
> **Architecture Decision**: The Supernote server pipeline uses the **Rendered Vision OCR** path (rendering layered pages to PNG and transcribing via vision LLMs) rather than relying on device-generated `RECOGNTEXT`, ensuring consistent transcription across Standard (non-real-time) notebooks, diagrams, and mixed handwriting.

---

## Writing & Reconstruction Caveats

[`reconstruct()` and `merge()`](../supernote/notebook/manipulator.py) rebuild valid latest-signature (`SN_FILE_VER_20230015`) `.note` streams and validate the result through `SupernoteXParser.parse_stream()`. Keep the following device constraints in mind when synthesizing notebooks programmatically:

- **`TOTALPATH` Vector Strokes**: Supernote firmware uses `TOTALPATH` for stroke-level erasing, lasso selection, and on-device re-recognition. Raster-only generated pages (`TOTALPATH=0`) display as bitmaps on `MAINLAYER` / `BGLAYER` but strokes are not individually editable on the device.
- **Opaque Header Parameters**: Hardware calibration tags such as `RATTA_ETMD`, `IS_OLD_APPLY_EQUIPMENT`, and `ANTIALIASING_CONVERT` carry device-specific values; prefer cloning `HeaderMetadata` from a template notebook matching the target `EquipmentType` rather than inventing values from scratch.
