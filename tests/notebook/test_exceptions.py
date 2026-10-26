import pytest

from supernote.notebook import exceptions


@pytest.mark.parametrize(
    ("exc_cls", "parent_cls"),
    [
        (exceptions.ParserException, exceptions.SupernoteLibException),
        (exceptions.UnsupportedFileFormat, exceptions.ParserException),
        (exceptions.DecoderException, exceptions.SupernoteLibException),
        (exceptions.UnknownDecodeProtocol, exceptions.DecoderException),
        (exceptions.ManipulatorException, exceptions.SupernoteLibException),
        (
            exceptions.GeneratedFileValidationException,
            exceptions.ManipulatorException,
        ),
    ],
)
def test_exception_hierarchy(
    exc_cls: type[Exception], parent_cls: type[Exception]
) -> None:
    assert issubclass(exc_cls, parent_cls)
    assert issubclass(exc_cls, exceptions.SupernoteLibException)
    err = exc_cls("test message")
    assert str(err) == "test message"
