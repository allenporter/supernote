# OCR Evaluation Report: `supernote-ocr-suite-v1` (20 pages)

## Overall Summary

| Target | Model | Pages | Mean CER | Median CER | Content CER | Word Recall | BuJo Symbol Recall | Median Latency | P95 Latency | Errors |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `apple:vision-accurate` | `vision-accurate` | 20 | 15.9% | 4.2% | 15.6% | 77.0% | 67.7% | 365.5 ms | 499.2 ms | 0 |
| `apple:vision-fast` | `vision-fast` | 20 | 65.3% | 81.7% | 65.0% | 24.1% | 12.2% | 113.2 ms | 160.0 ms | 0 |
| `device-rtr` | `supernote-rtr-embedded` | 3 | 4.3% | 1.9% | 4.3% | 98.8% | — | 0.0 ms | 0.0 ms | 0 |

## Breakdown by Category

| Target | Category | Pages | Mean CER | Content CER | Word Recall | BuJo Symbol Recall | BuJo Indent | BuJo Strike | Median Latency |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `apple:vision-accurate` | `bujo_daily` | 2 | 3.6% | 2.6% | 94.1% | 70.0% | 0.0% | 0.0% | 467.6 ms |
| `apple:vision-accurate` | `bujo_weekly` | 1 | 0.7% | 0.2% | 98.4% | 77.8% | 0.0% | — | 407.4 ms |
| `apple:vision-accurate` | `bujo_monthly` | 2 | 3.4% | 3.0% | 94.4% | 60.4% | 0.0% | 0.0% | 445.9 ms |
| `apple:vision-accurate` | `empty_template` | 1 | 0.0% | 0.0% | 100.0% | — | — | — | 131.7 ms |
| `apple:vision-accurate` | `english_prose` | 5 | 3.0% | 3.0% | 92.9% | — | — | — | 289.4 ms |
| `apple:vision-accurate` | `diagram_and_layout` | 4 | 21.9% | 21.3% | 64.2% | — | — | — | 398.6 ms |
| `apple:vision-accurate` | `multilingual` | 1 | 26.1% | 26.1% | 35.0% | — | — | — | 451.5 ms |
| `apple:vision-accurate` | `edge_cases` | 4 | 43.6% | 43.6% | 52.1% | — | — | — | 227.4 ms |
| `apple:vision-fast` | `bujo_daily` | 2 | 31.1% | 29.9% | 53.0% | 12.5% | 0.0% | 0.0% | 156.1 ms |
| `apple:vision-fast` | `bujo_weekly` | 1 | 18.6% | 16.6% | 62.9% | 11.1% | 0.0% | — | 143.1 ms |
| `apple:vision-fast` | `bujo_monthly` | 2 | 36.3% | 35.2% | 37.5% | 12.5% | 0.0% | 0.0% | 158.3 ms |
| `apple:vision-fast` | `empty_template` | 1 | 0.0% | 0.0% | 100.0% | — | — | — | 98.3 ms |
| `apple:vision-fast` | `english_prose` | 5 | 84.6% | 84.6% | 7.5% | — | — | — | 115.6 ms |
| `apple:vision-fast` | `diagram_and_layout` | 4 | 87.9% | 87.9% | 0.0% | — | — | — | 108.2 ms |
| `apple:vision-fast` | `multilingual` | 1 | 77.6% | 77.6% | 0.0% | — | — | — | 126.1 ms |
| `apple:vision-fast` | `edge_cases` | 4 | 75.0% | 75.0% | 25.0% | — | — | — | 100.1 ms |
| `device-rtr` | `english_prose` | 2 | 6.5% | 6.5% | 98.2% | — | — | — | 0.0 ms |
| `device-rtr` | `multilingual` | 1 | 0.0% | 0.0% | 100.0% | — | — | — | 0.0 ms |
