# Supernote notebook parsing and conversion

This package provides tools for parsing and converting Supernote `.note` files. It is recommended to use [supernote-tool](https://github.com/jya-dev/supernote-tool) instead unless you are having a similar dependency limitation motivation that led to this fork or if you prefer this API (type hints, higher test coverage, etc).

## Usage

### Parsing a Notebook

```python
from supernote.notebook import parse_notebook

notebook = parse_notebook("path/to/note.note")
```

### Converting to Formats

The `Notebook` object provides convenience methods for conversion:

```python
# Convert to PDF
data = notebook.to_pdf()
with open("output.pdf", "wb") as f:
    f.write(data)

# Convert to PNG (first page)
image = notebook.to_png(0)
image.save("page1.png")

# Convert to SVG (first page)
svg_string = notebook.to_svg(0)
```

### Accessing Metadata

You can access metadata and structure directly:

```python
# Total pages
print(notebook.get_total_pages())

# Page ID
print(notebook.get_page(0).get_pageid())

# Keywords
for keyword in notebook.get_keywords():
    print(keyword.get_keyword())
```

## Advanced Usage

For more control, you can use specific converters directly:

```python
from supernote.notebook import PdfConverter

converter = PdfConverter(notebook)
pdf_data = converter.convert(0) # Convert specific page
```
