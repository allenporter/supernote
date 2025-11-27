# supernote

The `supernote` library is a fork and slightly lighter dependency version of
[supernote-tool](https://github.com/jya-dev/supernote-tool) that drops svg
dependencies not found in some containers. Generally, you should probably
prefer to use that library unless there is a specific reason you're also
having a similar dependency limitation.

## Development

```
uv venv --python=3.14
source .venv/bin/activate
uv pip install -r requirements_dev.txt
```
