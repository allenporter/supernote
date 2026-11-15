# Supernote Test Corpus (`tests/testdata/`)

This directory contains real-world Supernote `.note` and `.mark` fixtures used for metadata schema validation, wire round-trip tests, page hash pinning, and visual/text regression snapshots.

## Attribution & Licenses

| Path / Directory | Upstream Source | License | Format Coverage |
| :--- | :--- | :--- | :--- |
| `20251207_221454.note` | Created in this repository | Apache-2.0 | `SN_FILE_VER_20230015` (`N6`) minimal 2-page notebook |
| `philips/` | [`philips/supernote-typescript`](https://github.com/philips/supernote-typescript) (`tests/input/`) | Apache-2.0 | `A5X`, `A6X`, `N5`, `N6` across `20220011`, `20230015`, `20260016` (orientations `1000`/`1090`/`1180`/`1270`, RTR locales, custom `user_*` PNG backgrounds, ruler/sticker/heading features) |
| `nelinory/` | [`nelinory/SupernoteSharp`](https://github.com/nelinory/SupernoteSharp) (`SupernoteSharpUnitTests/TestData/`) | MIT | `A5X` across `20220013` and `20230014` (`LINKO_*` / `LINKI_*` page, file, web, and typeset links, `PDFSTYLELIST` PDF templates, duplicate `STYLE_*` footer entries, `.pdf.mark` sidecar with `FIVESTAR` marks) |
| `schaefer-dev/` | [`schaefer-dev/supernote-viewer`](https://github.com/schaefer-dev/supernote-viewer) (`examples/`) | MIT | `SN_FILE_VER_20260016` (`N5`) `.pdf.mark` document annotation sidecar |
| `dsummersl/` | [`dsummersl/sn2md`](https://github.com/dsummersl/sn2md) | AGPL-3.0 | `SN_FILE_VER_20230015` (`N6`) multi-heading RTR notebook |
| `mmujynya/` | [`mmujynya/supernote-pdf`](https://github.com/mmujynya/supernote-pdf) | Unspecified | `SN_FILE_VER_20210010` (`A5X`) 5-page legacy Chauvet notebook |
