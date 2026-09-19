"""Own the shared private C01/C02 validation-error translation boundary."""

# standard library imports
from typing import NotRequired, Protocol, TypedDict

# third party library imports
from pydantic import TypeAdapter, ValidationError


class _ValidationErrorReader(Protocol):
    """Expose Pydantic error details as an unchecked boundary object."""

    def errors(
        self,
        *,
        include_url: bool = True,
        include_context: bool = True,
        include_input: bool = True,
    ) -> object:
        """Read error details for immediate validation into the owned record shape."""
        ...


class _ValidationErrorContext(TypedDict, total=False):
    """Capture optional context while retaining the original exception object."""

    error: object


class _ValidationErrorDetail(TypedDict):
    """Capture the Pydantic fields used in domain error messages."""

    loc: tuple[int | str, ...]
    msg: str
    ctx: NotRequired[_ValidationErrorContext]


class _ValidationMessages:
    """Translate redacted Pydantic details while preserving owned domain causes."""

    _details = TypeAdapter(list[_ValidationErrorDetail])

    @classmethod
    def from_error(cls, error: ValidationError, domain_error: type[ValueError]) -> str:
        """Join errors in field order, retaining messages from the supplied domain."""
        messages: list[str] = []
        error_reader: _ValidationErrorReader = error
        details = cls._details.validate_python(
            error_reader.errors(include_input=False, include_url=False), strict=True
        )
        for detail in details:
            context = detail.get("ctx")
            cause = context.get("error") if context is not None else None
            if isinstance(cause, domain_error):
                messages.append(str(cause))
                continue
            location = ".".join(str(component) for component in detail["loc"])
            message = detail["msg"].removeprefix("Value error, ")
            messages.append(f"{location}: {message}" if location else message)
        return "\n".join(messages)
