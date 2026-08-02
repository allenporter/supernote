---
name: project_development
description: Use standardized scripts to manage the project environment, testing, and linting.
---

# Project Development Skill

This skill teaches you how to interact with the Supernote codebase using standardized scripts, following the "Scripts to Rule Them All" pattern.

## Core Scripts

| Script | When to use |
| :--- | :--- |
| `script/bootstrap` | After cloning or when dependencies change. |
| `script/test` | Before submitting changes or to verify functionality. |
| `script/lint` | Before committing to ensure code style and quality. |
| `script/server` | When you need a running server for integration testing or manual verification. |
| `script/db_revision` | To generate a database migration revision. |

## Usage Patterns

### Standard Development Flow
1. **Initialize**: `./script/bootstrap`
2. **Implement**: Make your changes to the code.
3. **Database**: If you changed models, run `./script/db_revision "..."`.
4. **Lint**: `./script/lint` to check for style issues.
5. **Test**: `./script/test` to run the test suite.
6. **Verify**: `./script/server` to run an ephemeral server for manual checks.

### Notes
- All scripts are located in the `script/` directory at the project root.
- Scripts are designed to be run from the project root.
- The scripts will automatically use `uv` if it is installed, otherwise they will fall back to standard Python tools.

## Visual UI Testing Flow

To visually inspect and verify Web UI components rendered in a headless browser:

### 1. Install Prerequisites
Ensure OS shared libraries and Python Playwright package are installed:
```bash
apt-get install -y libgbm1 libasound2 libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libpango-1.0-0 libcairo2
uv pip install playwright
uv run playwright install chromium
```

### 2. Start Local Ephemeral Server
Run `./script/server` as a background task (`WaitMsBeforeAsync: 3000`). This starts the local server at `http://127.0.0.1:8080` with default user `debug@example.com` / `password`.

### 3. Capture & View Screenshot
Execute Playwright script via `run_command`:
```python
import asyncio
from playwright.async_api import async_playwright


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await page.goto("http://127.0.0.1:8080")
        await page.wait_for_timeout(1000)
        await page.fill("input[type=email]", "debug@example.com")
        await page.fill("input[type=password]", "password")
        await page.click("button[type=submit]")
        await page.wait_for_timeout(2000)
        screenshot_path = "<artifacts_dir>/ui_screenshot.png"
        await page.screenshot(path=screenshot_path)
        await browser.close()


asyncio.run(run())
```
Call `view_file` on the `.png` filepath to visually inspect and verify the rendered interface.
