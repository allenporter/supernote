# Supernote notebook parsing and conversion

This package provides tools for parsing and converting Supernote `.note` files. It originally started as a fork of [supernote-tool](https://github.com/jya-dev/supernote-tool) with lighter dependencies, modern type hints, and expanded test coverage.

## Usage

### Parsing a Notebook

```python
from supernote.notebook import parse_notebook

notebook = parse_notebook("path/to/note.note")
```

### Converting to Formats

Use the built-in converters (`PdfConverter`, `ImageConverter`, `SvgConverter`, `TextConverter`) to convert notebook pages:

```python
from pathlib import Path
from supernote.notebook import ImageConverter, PdfConverter, SvgConverter

# Convert all pages (-1) or a specific page index to PDF
pdf_data = PdfConverter(notebook).convert(-1)
Path("output.pdf").write_bytes(pdf_data)

# Convert first page to PNG (PIL Image)
image = ImageConverter(notebook).convert(0)
image.save("page1.png")

# Convert first page to SVG
svg_string = SvgConverter(notebook).convert(0)
```

### Accessing Metadata

You can access metadata and structure directly:

```python
# Total pages
print(notebook.total_pages)

# Page ID
print(notebook.page(0).page_id)

# Keywords
for keyword in notebook.keywords:
    print(keyword.keyword)
```

## Advanced Usage

For more control, you can use specific converters directly:

```python
from supernote.notebook import PdfConverter

converter = PdfConverter(notebook)
pdf_data = converter.convert(0)  # Convert specific page
```
