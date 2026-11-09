# OCR Evaluation Report: `supernote-ocr-suite-v1` (30 pages)

## Overall Summary

| Target | Model | Pages | Mean CER | Median CER | Content CER | Word Recall | BuJo Symbol Recall | Median Latency | P95 Latency | Errors |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `apple:vision-accurate` | `vision-accurate` | 30 | 21.7% | 9.8% | 21.1% | 76.5% | 45.8% | 410.8 ms | 665.8 ms | 0 |
| `apple:vision-fast` | `vision-fast` | 30 | 72.8% | 84.3% | 72.5% | 21.2% | 6.1% | 125.7 ms | 163.8 ms | 0 |
| `device-rtr` | `supernote-rtr-embedded` | 8 | 12.8% | 10.1% | 12.6% | 86.1% | 70.0% | 0.0 ms | 0.0 ms | 0 |
| `gemini:gemini-3.5-flash-lite` | `gemini-3.5-flash-lite` | 30 | 2.3% | 0.0% | 1.7% | 99.2% | 97.1% | 1179.1 ms | 1422.3 ms | 0 |
| `gemini:gemini-3.6-flash` | `gemini-3.6-flash` | 30 | 4.2% | 0.4% | 4.0% | 99.9% | 98.1% | 6626.1 ms | 17502.4 ms | 0 |
| `gemini:gemini-3.8-flash` | `gemini-3.8-flash` | 30 | 5.6% | 0.0% | 5.6% | 96.6% | 97.9% | 9932.0 ms | 40308.0 ms | 1 |
| `supernote-on-device` | `myscript-iink-4.1.0` | 25 | 17.2% | 3.3% | 17.1% | 80.1% | 62.5% | 909.0 ms | 1717.0 ms | 0 |

## Breakdown by Category

| Target | Category | Pages | Mean CER | Content CER | Word Recall | BuJo Symbol Recall | BuJo Indent | BuJo Strike | Median Latency |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `apple:vision-accurate` | `bujo_daily` | 3 | 8.9% | 5.8% | 89.4% | 46.7% | 0.0% | 0.0% | 440.0 ms |
| `apple:vision-accurate` | `bujo_weekly` | 1 | 0.7% | 0.2% | 98.4% | 77.8% | 0.0% | — | 393.1 ms |
| `apple:vision-accurate` | `bujo_monthly` | 4 | 26.6% | 25.3% | 72.8% | 43.3% | 0.0% | 0.0% | 526.9 ms |
| `apple:vision-accurate` | `empty_template` | 1 | 0.0% | 0.0% | 100.0% | — | — | — | 132.1 ms |
| `apple:vision-accurate` | `english_prose` | 5 | 3.0% | 3.0% | 92.9% | — | — | — | 291.9 ms |
| `apple:vision-accurate` | `diagram_and_layout` | 6 | 30.2% | 29.8% | 73.4% | 0.0% | — | — | 390.0 ms |
| `apple:vision-accurate` | `multilingual` | 6 | 24.6% | 24.4% | 70.9% | 55.0% | 0.0% | — | 609.7 ms |
| `apple:vision-accurate` | `edge_cases` | 4 | 43.6% | 43.6% | 52.1% | — | — | — | 387.8 ms |
| `apple:vision-fast` | `bujo_daily` | 3 | 49.6% | 48.5% | 35.3% | 8.3% | 0.0% | 0.0% | 163.8 ms |
| `apple:vision-fast` | `bujo_weekly` | 1 | 18.6% | 16.6% | 62.9% | 11.1% | 0.0% | — | 147.1 ms |
| `apple:vision-fast` | `bujo_monthly` | 4 | 61.3% | 60.6% | 25.9% | 8.3% | 0.0% | 0.0% | 136.8 ms |
| `apple:vision-fast` | `empty_template` | 1 | 0.0% | 0.0% | 100.0% | — | — | — | 98.7 ms |
| `apple:vision-fast` | `english_prose` | 5 | 84.6% | 84.6% | 7.5% | — | — | — | 114.6 ms |
| `apple:vision-fast` | `diagram_and_layout` | 6 | 90.5% | 90.5% | 5.6% | 0.0% | — | — | 115.8 ms |
| `apple:vision-fast` | `multilingual` | 6 | 84.3% | 84.1% | 15.6% | 0.0% | 0.0% | — | 137.6 ms |
| `apple:vision-fast` | `edge_cases` | 4 | 75.0% | 75.0% | 25.0% | — | — | — | 102.7 ms |
| `device-rtr` | `english_prose` | 2 | 6.5% | 6.5% | 98.2% | — | — | — | 0.0 ms |
| `device-rtr` | `multilingual` | 6 | 15.0% | 14.6% | 82.1% | 70.0% | 0.0% | — | 0.0 ms |
| `gemini:gemini-3.5-flash-lite` | `bujo_daily` | 3 | 0.6% | 0.3% | 98.3% | 93.3% | 100.0% | 100.0% | 1213.7 ms |
| `gemini:gemini-3.5-flash-lite` | `bujo_weekly` | 1 | 0.0% | 0.0% | 100.0% | 100.0% | 100.0% | — | 1028.3 ms |
| `gemini:gemini-3.5-flash-lite` | `bujo_monthly` | 4 | 0.2% | 0.0% | 100.0% | 97.0% | 100.0% | 100.0% | 1328.9 ms |
| `gemini:gemini-3.5-flash-lite` | `empty_template` | 1 | 0.0% | 0.0% | 100.0% | — | — | — | 1422.9 ms |
| `gemini:gemini-3.5-flash-lite` | `english_prose` | 5 | 0.0% | 0.0% | 100.0% | — | — | — | 1104.6 ms |
| `gemini:gemini-3.5-flash-lite` | `diagram_and_layout` | 6 | 4.5% | 2.9% | 99.5% | 100.0% | — | — | 1238.7 ms |
| `gemini:gemini-3.5-flash-lite` | `multilingual` | 6 | 5.0% | 5.0% | 97.2% | 100.0% | 100.0% | — | 1155.1 ms |
| `gemini:gemini-3.5-flash-lite` | `edge_cases` | 4 | 2.2% | 0.4% | 100.0% | — | — | — | 831.0 ms |
| `gemini:gemini-3.6-flash` | `bujo_daily` | 3 | 0.2% | 0.1% | 100.0% | 96.7% | 100.0% | 100.0% | 6630.0 ms |
| `gemini:gemini-3.6-flash` | `bujo_weekly` | 1 | 0.0% | 0.0% | 100.0% | 100.0% | 100.0% | — | 6622.2 ms |
| `gemini:gemini-3.6-flash` | `bujo_monthly` | 4 | 0.7% | 0.4% | 100.0% | 97.0% | 100.0% | 100.0% | 8544.6 ms |
| `gemini:gemini-3.6-flash` | `empty_template` | 1 | 0.0% | 0.0% | 100.0% | — | — | — | 3077.2 ms |
| `gemini:gemini-3.6-flash` | `english_prose` | 5 | 0.0% | 0.0% | 100.0% | — | — | — | 4612.2 ms |
| `gemini:gemini-3.6-flash` | `diagram_and_layout` | 6 | 14.5% | 14.5% | 99.5% | 100.0% | — | — | 6868.5 ms |
| `gemini:gemini-3.6-flash` | `multilingual` | 6 | 2.3% | 2.4% | 99.8% | 100.0% | 100.0% | — | 10574.6 ms |
| `gemini:gemini-3.6-flash` | `edge_cases` | 4 | 5.6% | 3.8% | 100.0% | — | — | — | 4035.8 ms |
| `gemini:gemini-3.8-flash` | `bujo_daily` | 3 | 0.3% | 0.2% | 100.0% | 96.7% | 100.0% | 100.0% | 13304.2 ms |
| `gemini:gemini-3.8-flash` | `bujo_weekly` | 1 | 0.0% | 0.0% | 100.0% | 100.0% | 100.0% | — | 8136.2 ms |
| `gemini:gemini-3.8-flash` | `bujo_monthly` | 4 | 0.5% | 0.3% | 100.0% | 97.0% | 100.0% | 100.0% | 12297.9 ms |
| `gemini:gemini-3.8-flash` | `empty_template` | 1 | 0.0% | 0.0% | 100.0% | — | — | — | 4500.2 ms |
| `gemini:gemini-3.8-flash` | `english_prose` | 5 | 0.1% | 0.1% | 100.0% | — | — | — | 4512.4 ms |
| `gemini:gemini-3.8-flash` | `diagram_and_layout` | 6 | 22.9% | 22.9% | 83.3% | — | — | — | 17088.0 ms |
| `gemini:gemini-3.8-flash` | `multilingual` | 6 | 2.1% | 2.2% | 99.6% | 100.0% | 100.0% | — | 16308.3 ms |
| `gemini:gemini-3.8-flash` | `edge_cases` | 4 | 3.8% | 3.8% | 100.0% | — | — | — | 5806.2 ms |
| `supernote-on-device` | `bujo_daily` | 1 | 7.4% | 7.2% | 95.0% | 10.0% | — | — | 917.0 ms |
| `supernote-on-device` | `bujo_monthly` | 2 | 13.2% | 12.2% | 79.6% | 27.3% | 66.7% | 0.0% | 979.0 ms |
| `supernote-on-device` | `empty_template` | 1 | 0.0% | 0.0% | 100.0% | — | — | — | 103.0 ms |
| `supernote-on-device` | `english_prose` | 5 | 1.2% | 1.2% | 99.1% | — | — | — | 509.0 ms |
| `supernote-on-device` | `diagram_and_layout` | 6 | 24.6% | 24.6% | 68.1% | 100.0% | — | — | 606.0 ms |
| `supernote-on-device` | `multilingual` | 6 | 4.4% | 4.2% | 94.9% | 87.5% | 75.0% | — | 1611.0 ms |
| `supernote-on-device` | `edge_cases` | 4 | 54.0% | 54.0% | 43.8% | — | — | — | 203.0 ms |
