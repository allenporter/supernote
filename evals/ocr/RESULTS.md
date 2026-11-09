# OCR Evaluation Report: `supernote-ocr-suite-v1` (30 pages)

## Overall Summary

| Target | Model | Pages | Mean CER | Median CER | Content CER | Word F1 | Word Recall | BuJo Symbol Recall | Median Latency | P95 Latency | Errors |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `apple:vision-accurate` | `vision-accurate` | 30 | 21.7% | 9.8% | 20.7% | 73.7% | 71.0% | 49.7% | 410.8 ms | 665.8 ms | 0 |
| `apple:vision-fast` | `vision-fast` | 30 | 72.8% | 84.3% | 70.7% | 17.8% | 17.0% | 8.7% | 125.7 ms | 163.8 ms | 0 |
| `device-rtr` | `supernote-rtr-embedded` | 8 | 12.8% | 10.1% | 12.0% | 77.7% | 80.4% | — | 0.0 ms | 0.0 ms | 0 |
| `gemini:gemini-3.5-flash-lite` | `gemini-3.5-flash-lite` | 30 | 2.3% | 0.0% | 1.4% | 99.0% | 99.1% | 95.8% | 1179.1 ms | 1422.3 ms | 0 |
| `gemini:gemini-3.6-flash` | `gemini-3.6-flash` | 30 | 4.2% | 0.4% | 3.6% | 99.7% | 99.8% | 97.3% | 6626.1 ms | 17502.4 ms | 0 |
| `gemini:gemini-3.8-flash` | `gemini-3.8-flash` | 30 | 5.6% | 0.0% | 5.4% | 96.5% | 96.5% | 97.3% | 9932.0 ms | 40308.0 ms | 1 |
| `supernote-on-device` | `myscript-iink-4.1.0` | 25 | 17.2% | 3.3% | 16.7% | 75.5% | 73.8% | 18.6% | 909.0 ms | 1717.0 ms | 0 |

## Breakdown by Category

| Target | Category | Pages | Mean CER | Content CER | Word F1 | Word Recall | BuJo Symbol Recall | BuJo Indent | BuJo Strike | Median Latency |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `apple:vision-accurate` | `bujo_synthetic` | 5 | 2.9% | 2.0% | 94.4% | 95.0% | 67.7% | 0.0% | 0.0% | 405.6 ms |
| `apple:vision-accurate` | `bujo_daily` | 1 | 19.5% | 11.3% | 74.4% | 72.5% | 0.0% | — | — | 617.7 ms |
| `apple:vision-accurate` | `bujo_monthly` | 2 | 49.7% | 46.2% | 56.4% | 49.2% | 9.1% | 0.0% | 0.0% | 608.9 ms |
| `apple:vision-accurate` | `empty_template` | 1 | 0.0% | 0.0% | 100.0% | 100.0% | — | — | — | 132.1 ms |
| `apple:vision-accurate` | `english_prose` | 5 | 3.0% | 2.7% | 93.0% | 93.0% | — | — | — | 291.9 ms |
| `apple:vision-accurate` | `diagram_and_layout` | 6 | 30.2% | 29.4% | 64.1% | 58.2% | — | — | — | 390.0 ms |
| `apple:vision-accurate` | `multilingual` | 6 | 24.6% | 23.7% | 64.5% | 61.3% | — | — | — | 609.7 ms |
| `apple:vision-accurate` | `edge_cases` | 4 | 43.6% | 43.6% | 53.4% | 50.8% | — | — | — | 387.8 ms |
| `apple:vision-fast` | `bujo_synthetic` | 5 | 30.7% | 26.7% | 47.6% | 48.1% | 12.2% | 0.0% | 0.0% | 155.0 ms |
| `apple:vision-fast` | `bujo_daily` | 1 | 86.5% | 84.6% | 0.0% | 0.0% | 0.0% | — | — | 179.7 ms |
| `apple:vision-fast` | `bujo_monthly` | 2 | 86.4% | 83.5% | 11.0% | 7.2% | 0.0% | 0.0% | 0.0% | 122.4 ms |
| `apple:vision-fast` | `empty_template` | 1 | 0.0% | 0.0% | 100.0% | 100.0% | — | — | — | 98.7 ms |
| `apple:vision-fast` | `english_prose` | 5 | 84.6% | 81.8% | 7.1% | 5.9% | — | — | — | 114.6 ms |
| `apple:vision-fast` | `diagram_and_layout` | 6 | 90.5% | 89.5% | 1.8% | 1.0% | — | — | — | 115.8 ms |
| `apple:vision-fast` | `multilingual` | 6 | 84.3% | 81.8% | 4.5% | 3.2% | — | — | — | 137.6 ms |
| `apple:vision-fast` | `edge_cases` | 4 | 75.0% | 74.6% | 25.0% | 25.0% | — | — | — | 102.7 ms |
| `device-rtr` | `english_prose` | 2 | 6.5% | 5.8% | 96.0% | 96.9% | — | — | — | 0.0 ms |
| `device-rtr` | `multilingual` | 6 | 15.0% | 14.0% | 71.6% | 74.9% | — | — | — | 0.0 ms |
| `gemini:gemini-3.5-flash-lite` | `bujo_synthetic` | 5 | 0.0% | 0.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 1316.4 ms |
| `gemini:gemini-3.5-flash-lite` | `bujo_daily` | 1 | 1.9% | 1.0% | 92.7% | 95.0% | 80.0% | — | — | 1003.2 ms |
| `gemini:gemini-3.5-flash-lite` | `bujo_monthly` | 2 | 0.5% | 0.0% | 100.0% | 100.0% | 90.9% | 100.0% | 100.0% | 1319.8 ms |
| `gemini:gemini-3.5-flash-lite` | `empty_template` | 1 | 0.0% | 0.0% | 100.0% | 100.0% | — | — | — | 1422.9 ms |
| `gemini:gemini-3.5-flash-lite` | `english_prose` | 5 | 0.0% | 0.0% | 100.0% | 100.0% | — | — | — | 1104.6 ms |
| `gemini:gemini-3.5-flash-lite` | `diagram_and_layout` | 6 | 4.5% | 2.2% | 99.0% | 99.4% | — | — | — | 1238.7 ms |
| `gemini:gemini-3.5-flash-lite` | `multilingual` | 6 | 5.0% | 4.8% | 97.1% | 97.1% | — | — | — | 1155.1 ms |
| `gemini:gemini-3.5-flash-lite` | `edge_cases` | 4 | 2.2% | 0.0% | 100.0% | 100.0% | — | — | — | 831.0 ms |
| `gemini:gemini-3.6-flash` | `bujo_synthetic` | 5 | 0.1% | 0.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 6622.2 ms |
| `gemini:gemini-3.6-flash` | `bujo_daily` | 1 | 0.5% | 0.0% | 100.0% | 100.0% | 90.0% | — | — | 6630.0 ms |
| `gemini:gemini-3.6-flash` | `bujo_monthly` | 2 | 1.3% | 0.6% | 100.0% | 100.0% | 90.9% | 100.0% | 100.0% | 9704.2 ms |
| `gemini:gemini-3.6-flash` | `empty_template` | 1 | 0.0% | 0.0% | 100.0% | 100.0% | — | — | — | 3077.2 ms |
| `gemini:gemini-3.6-flash` | `english_prose` | 5 | 0.0% | 0.0% | 100.0% | 100.0% | — | — | — | 4612.2 ms |
| `gemini:gemini-3.6-flash` | `diagram_and_layout` | 6 | 14.5% | 13.8% | 99.3% | 99.5% | — | — | — | 6868.5 ms |
| `gemini:gemini-3.6-flash` | `multilingual` | 6 | 2.3% | 2.1% | 99.4% | 99.5% | — | — | — | 10574.6 ms |
| `gemini:gemini-3.6-flash` | `edge_cases` | 4 | 5.6% | 3.3% | 100.0% | 100.0% | — | — | — | 4035.8 ms |
| `gemini:gemini-3.8-flash` | `bujo_synthetic` | 5 | 0.0% | 0.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 10365.9 ms |
| `gemini:gemini-3.8-flash` | `bujo_daily` | 1 | 0.9% | 0.0% | 100.0% | 100.0% | 90.0% | — | — | 16975.6 ms |
| `gemini:gemini-3.8-flash` | `bujo_monthly` | 2 | 1.0% | 0.6% | 100.0% | 100.0% | 90.9% | 100.0% | 100.0% | 14882.3 ms |
| `gemini:gemini-3.8-flash` | `empty_template` | 1 | 0.0% | 0.0% | 100.0% | 100.0% | — | — | — | 4500.2 ms |
| `gemini:gemini-3.8-flash` | `english_prose` | 5 | 0.1% | 0.0% | 100.0% | 100.0% | — | — | — | 4512.4 ms |
| `gemini:gemini-3.8-flash` | `diagram_and_layout` | 6 | 22.9% | 22.5% | 83.3% | 83.3% | — | — | — | 17088.0 ms |
| `gemini:gemini-3.8-flash` | `multilingual` | 6 | 2.1% | 1.9% | 99.1% | 99.4% | — | — | — | 16308.3 ms |
| `gemini:gemini-3.8-flash` | `edge_cases` | 4 | 3.8% | 3.3% | 100.0% | 100.0% | — | — | — | 5806.2 ms |
| `supernote-on-device` | `bujo_daily` | 1 | 7.4% | 7.2% | 92.5% | 92.5% | 10.0% | — | — | 917.0 ms |
| `supernote-on-device` | `bujo_monthly` | 2 | 13.2% | 11.7% | 71.4% | 68.5% | 27.3% | 66.7% | 0.0% | 979.0 ms |
| `supernote-on-device` | `empty_template` | 1 | 0.0% | 0.0% | 100.0% | 100.0% | — | — | — | 103.0 ms |
| `supernote-on-device` | `english_prose` | 5 | 1.2% | 1.0% | 97.8% | 98.1% | — | — | — | 509.0 ms |
| `supernote-on-device` | `diagram_and_layout` | 6 | 24.6% | 23.8% | 55.2% | 50.6% | — | — | — | 606.0 ms |
| `supernote-on-device` | `multilingual` | 6 | 4.4% | 4.1% | 93.9% | 92.9% | — | — | — | 1611.0 ms |
| `supernote-on-device` | `edge_cases` | 4 | 54.0% | 53.6% | 42.5% | 40.9% | — | — | — | 203.0 ms |
