"""Locator system — the core abstraction for finding UI elements.

Provides a hierarchy of locator types together with a factory for constructing
locators from strings, dictionaries, or existing instances.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, Type, Union

from mocharpa.core.element import Rectangle

# Shorthand type for anything that can be turned into a locator.
LocatorSpec = Union[str, Dict[str, Any], "Locator"]


# ======================================================================
# Abstract base
# ======================================================================

class Locator(ABC):
    """Abstract base for all element locators.

    Subclasses must implement :meth:`matches` for runtime filtering and
    :meth:`to_dict` / :meth:`from_dict` for serialisation.
    """

    def __and__(self, other: Locator) -> LocatorChain:
        """Combine two locators so both must match (AND)."""
        own = self.locators if isinstance(self, LocatorChain) else (self,)
        other_locators = other.locators if isinstance(other, LocatorChain) else (other,)
        return LocatorChain(own + other_locators)

    @abstractmethod
    def matches(self, element: Any) -> bool:
        """Return True if *element* satisfies this locator."""

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary."""

    @classmethod
    @abstractmethod
    def from_dict(cls, data: Dict[str, Any]) -> Locator:
        """Reconstruct from a dictionary."""


# ======================================================================
# Concrete locators
# ======================================================================

@dataclass(frozen=True)
class ById(Locator):
    """Match an element by its automation / accessibility ID."""

    value: str

    def matches(self, element: Any) -> bool:
        aid = getattr(element, "AutomationId", None)
        if aid is not None:
            return str(aid) == self.value
        return getattr(element, "automation_id", "") == self.value

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "id", "value": self.value}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ById:
        return cls(value=data["value"])

    def __repr__(self) -> str:
        return f"ById({self.value!r})"


@dataclass(frozen=True)
class ByName(Locator):
    """Match an element by its human-readable name.

    Args:
        value: Name pattern to match.
        exact: If True, require an exact match; otherwise substring match.
    """

    value: str
    exact: bool = True

    def matches(self, element: Any) -> bool:
        name = getattr(element, "Name", None) or ""
        if self.exact:
            return name == self.value
        return self.value.lower() in name.lower()

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "name", "value": self.value, "exact": self.exact}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ByName:
        return cls(value=data["value"], exact=data.get("exact", True))

    def __repr__(self) -> str:
        exact = "" if self.exact else ", exact=False"
        return f"ByName({self.value!r}{exact})"


@dataclass(frozen=True)
class ByType(Locator):
    """Match an element by its control type (e.g. 'Button', 'Edit')."""

    value: str

    def matches(self, element: Any) -> bool:
        ct = getattr(element, "ControlTypeName", None)
        if ct is not None:
            return ct.lower() == self.value.lower()
        ct = getattr(element, "control_type", "")
        return ct.lower() == self.value.lower()

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "type", "value": self.value}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ByType:
        return cls(value=data["value"])

    def __repr__(self) -> str:
        return f"ByType({self.value!r})"


@dataclass(frozen=True)
class ByClass(Locator):
    """Match an element by its class name."""

    value: str

    def matches(self, element: Any) -> bool:
        cn = getattr(element, "ClassName", "") or getattr(element, "class_name", "")
        return cn == self.value or self.value in cn

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "class", "value": self.value}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ByClass:
        return cls(value=data["value"])

    def __repr__(self) -> str:
        return f"ByClass({self.value!r})"


@dataclass(frozen=True)
class ByRegion(Locator):
    """Match an element whose bounding rectangle lies within (or overlaps) a region."""

    rect: Rectangle

    def matches(self, element: Any) -> bool:
        try:
            er = element.BoundingRectangle
            elem_rect = Rectangle(er.left, er.top, er.width, er.height)
        except AttributeError:
            elem_rect = getattr(element, "bounding_rectangle", Rectangle(0, 0, 0, 0))
        return self.rect.overlaps(elem_rect)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "region",
            "left": self.rect.left,
            "top": self.rect.top,
            "width": self.rect.width,
            "height": self.rect.height,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ByRegion:
        return cls(
            rect=Rectangle(
                left=data["left"],
                top=data["top"],
                width=data["width"],
                height=data["height"],
            )
        )

    def __repr__(self) -> str:
        return f"ByRegion({self.rect})"


@dataclass(frozen=True)
class ByImage(Locator):
    """Match an element using image template matching.

    Args:
        path: Filesystem path to the template image.
        confidence: Minimum similarity threshold (0.0–1.0).
    """

    path: str
    confidence: float = 0.85

    def matches(self, element: Any) -> bool:
        # Stub — image matching requires a driver with screenshot capability.
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "image", "path": self.path, "confidence": self.confidence}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ByImage:
        return cls(path=data["path"], confidence=data.get("confidence", 0.85))

    def __repr__(self) -> str:
        return f"ByImage(path={self.path!r}, confidence={self.confidence})"


# ======================================================================
# Locator chain
# ======================================================================

@dataclass(frozen=True)
class LocatorChain(Locator):
    """Composite locator that requires ALL child locators to match (logical AND).

    Constructed implicitly via ``loc1 & loc2`` or explicitly by passing a tuple.
    """

    locators: tuple[Locator, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if len(self.locators) < 2:
            raise ValueError("LocatorChain requires at least two locators")

    def matches(self, element: Any) -> bool:
        return all(loc.matches(element) for loc in self.locators)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "chain", "locators": [loc.to_dict() for loc in self.locators]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LocatorChain:
        locators = tuple(LocatorFactory.create(item) for item in data["locators"])
        return cls(locators=locators)

    def __repr__(self) -> str:
        items = " & ".join(repr(loc) for loc in self.locators)
        return f"LocatorChain({items})"


# ======================================================================
# Factory
# ======================================================================

class LocatorFactory:
    """Factory that creates :class:`Locator` instances from various formats.

    Supported input formats:

    * **string** — ``"name:OK"``, ``"id:btn1"``, ``"type:Button"``
    * **dict** — ``{"type": "name", "value": "OK"}``
    * **Locator** — returned as-is

    Chain syntax via ``>``: ``"name:Login > type:Window"`` creates a LocatorChain.

    Custom locator types can be registered via :meth:`register`.
    """

    _registry: ClassVar[Dict[str, Type[Locator]]] = {
        "id": ById,
        "name": ByName,
        "type": ByType,
        "class": ByClass,
        "region": ByRegion,
        "image": ByImage,
        "chain": LocatorChain,
    }

    SEPARATOR: ClassVar[str] = ">"

    @classmethod
    def register(cls, type_name: str, klass: Type[Locator]) -> None:
        """Register a custom locator type.

        Args:
            type_name: Unique string identifier (e.g. ``"custom"``).
            klass: Locator subclass.
        """
        if not issubclass(klass, Locator):
            raise TypeError(f"{klass.__name__} must be a subclass of Locator")
        cls._registry[type_name] = klass

    @classmethod
    def create(cls, spec: LocatorSpec) -> Locator:
        """Create a locator from *spec*.

        Returns:
            A :class:`Locator` instance (or :class:`LocatorChain` for ``>`` strings).
        """
        if isinstance(spec, Locator):
            return spec

        if isinstance(spec, str):
            parts = [p.strip() for p in spec.split(cls.SEPARATOR) if p.strip()]
            if len(parts) > 1:
                return LocatorChain(tuple(cls._parse_str(p) for p in parts))
            return cls._parse_str(parts[0])

        if isinstance(spec, dict):
            type_name = spec.get("type", "name")
            klass = cls._registry.get(type_name)
            if klass is None:
                raise ValueError(
                    f"Unknown locator type '{type_name}'. "
                    f"Registered types: {list(cls._registry)}"
                )
            return klass.from_dict(spec)

        raise TypeError(f"Cannot create locator from {type(spec).__name__}: {spec!r}")

    @classmethod
    def _parse_str(cls, raw: str) -> Locator:
        """Parse a single ``type:value`` string."""
        if ":" not in raw:
            # Default to name lookup
            return ByName(value=raw, exact=True)

        type_name, value = raw.split(":", 1)
        type_name = type_name.strip().lower()
        value = value.strip()

        klass = cls._registry.get(type_name)
        if klass is None:
            raise ValueError(
                f"Unknown locator type '{type_name}' in '{raw}'. "
                f"Registered: {list(cls._registry)}"
            )

        return klass.from_dict({"type": type_name, "value": value})

    @classmethod
    def list_types(cls) -> Dict[str, Type[Locator]]:
        """Return a copy of the registered locator types."""
        return dict(cls._registry)
