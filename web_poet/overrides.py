from __future__ import annotations  # https://www.python.org/dev/peps/pep-0563/

import importlib
import importlib.util
import warnings
import pkgutil
from collections import deque
from dataclasses import dataclass, field
from operator import attrgetter
from typing import Iterable, Optional, Union, List, Callable, Dict, Any

from url_matcher import Patterns

Strings = Union[str, Iterable[str]]


@dataclass(frozen=True)
class OverrideRule:
    """A single override rule that specifies when a Page Object should be used
    instead of another.

    This is instantiated when using the :func:`web_poet.handle_urls` decorator.
    It's also being returned as a ``List[OverrideRule]`` when calling
    :meth:`~.PageObjectRegistry.get_overrides`.

    You can access any of its attributes:

        * ``for_patterns: Patterns`` - contains the URL patterns associated
          with this rule. You can read the API documentation of the
          `url-matcher <https://url-matcher.readthedocs.io/>`_ package for more
          information.
        * ``use: Callable`` - the Page Object that will be used.
        * ``instead_of: Callable`` - the Page Object that will be **replaced**.
        * ``meta: Dict[str, Any] = field(default_factory=dict)`` - Any other
          information you many want to store. This doesn't do anything for now
          but may be useful for future API updates.
    """

    for_patterns: Patterns
    use: Callable
    instead_of: Callable
    meta: Dict[str, Any] = field(default_factory=dict)

    def __hash__(self):
        return hash((self.for_patterns, self.use, self.instead_of))


def _as_list(value: Optional[Strings]) -> List[str]:
    """
    >>> _as_list(None)
    []
    >>> _as_list("foo")
    ['foo']
    >>> _as_list(["foo", "bar"])
    ['foo', 'bar']
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


class PageObjectRegistry:
    """This contains the mapping rules that associates the Page Objects available
    for a given URL matching rule.

    ``web-poet`` already provides a default Registry name ``default_registry``
    for convenience. It can be directly accessed via:

    .. code-block:: python

        from web_poet import handle_urls, default_registry

        @handle_urls("example.com", overrides=ProductPageObject)
        class ExampleComProductPage(ItemPage):
            ...

        override_rules = default_registry.get_overrides()

    Notice that the ``handle_urls`` that we've imported is a part of
    ``default_registry``. This provides a shorter and quicker way to interact
    with the built-in default Registry.

    .. note::

        It is encouraged to simply use and import the already existing registry
        via ``from web_poet import default_registry`` instead of creating your
        own :class:`~.PageObjectRegistry` instance. Using multiple registries
        would be unwieldy in general cases. However, it could be applicable in
        certain scenarios.
    """

    def __init__(self):
        self._data: Dict[Callable, OverrideRule] = {}

    def handle_urls(
        self,
        include: Strings,
        overrides: Callable,
        *,
        exclude: Optional[Strings] = None,
        priority: int = 500,
        **kwargs,
    ):
        """
        Class decorator that indicates that the decorated Page Object should be
        used instead of the overridden one for a particular set the URLs.

        Which Page Object is overridden is determined by the ``overrides``
        parameter.

        Over which URLs the override happens is determined by the ``include``,
        ``exclude`` and ``priority`` parameters. See the documentation of the
        `url-matcher <https://url-matcher.readthedocs.io/>`_ package for more
        information about them.

        Any extra parameters are stored as meta information that can be later used.

        :param include: Defines the URLs that should be handled by the overridden Page Object.
        :param overrides: The Page Object that should be replaced by the annotated one.
        :param exclude: Defines URLs over which the override should not happen.
        :param priority: The resolution priority in case of conflicting annotations.
        """

        def wrapper(cls):
            rule = OverrideRule(
                for_patterns=Patterns(
                    include=_as_list(include),
                    exclude=_as_list(exclude),
                    priority=priority,
                ),
                use=cls,
                instead_of=overrides,
                meta=kwargs,
            )
            # If it was already defined, we don't want to override it
            if cls not in self._data:
                self._data[cls] = rule
            else:
                warnings.warn(
                    f"Multiple @handle_urls annotations with the same 'overrides' "
                    f"are ignored in the same Registry. Ignoring duplicate "
                    f"annotation on '{include}' for {cls}."
                )

            return cls

        return wrapper

    def get_overrides(self, consume: Optional[Strings] = None) -> List[OverrideRule]:
        """Returns a ``List`` of :class:`~.OverrideRule` that were declared using
        ``@handle_urls``.

        :param consume: packages/modules that need to be imported so that it can
            properly load the :meth:`~.PageObjectRegistry.handle_urls` annotations.

        .. warning::

            Remember to consider using the ``consume`` parameter to properly load
            the :meth:`~.PageObjectRegistry.handle_urls` from external Page
            Objects

            The ``consume`` parameter provides a convenient shortcut for calling
            :func:`~.web_poet.overrides.consume_modules`.
        """
        if consume:
            consume_modules(*_as_list(consume))

        return list(self._data.values())

    def search_overrides(self, **kwargs) -> List[OverrideRule]:
        """Returns a list of :class:`OverrideRule` if any of the attributes
        matches the rules inside the registry.

        Sample usage:

        .. code-block:: python

            rules = registry.search_overrides(use=ProductPO, instead_of=GenericPO)
            print(len(rules))  # 1

        """

        # Short-circuit operation if "use" is the only search param used, since
        # we know that it's being used as the dict key.
        if set(["use"]) == kwargs.keys():
            rule = self._data.get(kwargs["use"])
            if rule:
                return [rule]
            return []

        getter = attrgetter(*kwargs.keys())

        def matcher(rule: OverrideRule):
            attribs = getter(rule)
            if not isinstance(attribs, tuple):
                attribs = tuple([attribs])
            if list(attribs) == list(kwargs.values()):
                return True
            return False

        results = []
        for rule in self.get_overrides():
            if matcher(rule):
                results.append(rule)
        return results


def walk_module(module: str) -> Iterable:
    """Return all modules from a module recursively.

    Note that this will import all the modules and submodules. It returns the
    provided module as well.
    """

    def onerror(err):
        raise err  # pragma: no cover

    spec = importlib.util.find_spec(module)
    if not spec:
        raise ImportError(f"Module {module} not found")
    mod = importlib.import_module(spec.name)
    yield mod
    if spec.submodule_search_locations:
        for info in pkgutil.walk_packages(
            spec.submodule_search_locations, f"{spec.name}.", onerror
        ):
            mod = importlib.import_module(info.name)
            yield mod


def consume_modules(*modules: str) -> None:
    """A quick wrapper for :func:`~.walk_module` to efficiently consume the
    generator and recursively load all packages/modules.

    This function is essential to be run before attempting to retrieve all
    :meth:`~.PageObjectRegistry.handle_urls` annotations from :class:`~.PageObjectRegistry`
    to ensure that they are properly acknowledged by importing them in runtime.

    Let's take a look at an example:

    .. code-block:: python

        # my_page_obj_project/load_rules.py

        from web_poet import default_registry, consume_modules

        consume_modules("other_external_pkg.po", "another_pkg.lib")
        rules = default_registry.get_overrides()

    For this case, the ``List`` of :class:`~.OverrideRule` are coming from:

        - ``my_page_obj_project`` `(since it's the same module as the file above)`
        - ``other_external_pkg.po``
        - ``another_pkg.lib``

    So if the ``default_registry`` had other ``@handle_urls`` annotations outside
    of the packages/modules listed above, then the :class:`~.OverrideRule` won't
    be returned.

    .. note::

        :meth:`~.PageObjectRegistry.get_overrides` provides a shortcut for this
        using its ``consume`` parameter. Thus, the code example above could be
        shortened even further by:

        .. code-block:: python

            from web_poet import default_registry

            rules = default_registry.get_overrides(consume=["other_external_pkg.po", "another_pkg.lib"])
    """

    for module in modules:
        gen = walk_module(module)

        # Inspired by itertools recipe: https://docs.python.org/3/library/itertools.html
        # Using a deque() results in a tiny bit performance improvement that list().
        deque(gen, maxlen=0)
