import abc
from typing import Union
from urllib.parse import urljoin

import parsel
from w3lib.html import get_base_url

from web_poet.page_inputs.url import RequestUrl, ResponseUrl


class SelectableMixin(abc.ABC):
    """
    Inherit from this mixin, implement ``._selector_input`` method,
    get ``.selector`` property and ``.xpath`` / ``.css`` methods.
    """

    __cached_selector = None

    @abc.abstractmethod
    def _selector_input(self) -> str:
        raise NotImplementedError()  # pragma: nocover

    @property
    def selector(self) -> parsel.Selector:
        """Cached instance of :external:class:`parsel.selector.Selector`."""
        # XXX: caching is implemented in a manual way to avoid issues with
        # non-hashable classes, where memoizemethod_noargs doesn't work
        if self.__cached_selector is not None:
            return self.__cached_selector
        # XXX: should we pass base_url=self.url, as Scrapy does?
        sel = parsel.Selector(text=self._selector_input())
        self.__cached_selector = sel
        return sel

    def xpath(self, query, **kwargs) -> parsel.SelectorList:
        """A shortcut to ``.selector.xpath()``."""
        return self.selector.xpath(query, **kwargs)

    def css(self, query) -> parsel.SelectorList:
        """A shortcut to ``.selector.css()``."""
        return self.selector.css(query)


# TODO: when dropping Python 3.7 support,
# fix untyped ResponseShortcutsMixin.response using typing.Protocol


class ResponseShortcutsMixin(SelectableMixin):
    """Common shortcut methods for working with HTML responses.
    This mixin could be used with Page Object base classes.

    It requires "response" attribute to be present.
    """

    _cached_base_url = None

    @property
    def url(self):
        """Shortcut to HTML Response's URL, as a string."""
        return str(self.response.url)

    @property
    def html(self):
        """Shortcut to HTML Response's content."""
        return self.response.text

    def _selector_input(self) -> str:
        return self.html

    @property
    def base_url(self) -> str:
        """Return the base url of the given response"""
        # FIXME: move it to HttpResponse
        if self._cached_base_url is None:
            text = self.html[:4096]
            self._cached_base_url = get_base_url(text, self.url)
        return self._cached_base_url

    def urljoin(self, url: str) -> str:
        """Convert url to absolute, taking in account
        url and baseurl of the response"""
        # FIXME: move it to HttpResponse
        return urljoin(self.base_url, url)


class UrlMixin(abc.ABC):
    """Common shortcut methods for working with the URL of HTTP requests and
    responses.

    This mixin could be used with Page Object base classes.

    It requires the ``url`` attribute to be present.
    """

    _cached_base_url = None
    url: Union[str, RequestUrl, ResponseUrl]

    @property
    def _base_url(self) -> str:
        if self._cached_base_url is None:
            text = getattr(self, "text", "")[:4096]
            self._cached_base_url = get_base_url(text, str(self.url))
        return self._cached_base_url

    def urljoin(self, url: Union[str, RequestUrl, ResponseUrl]) -> RequestUrl:
        """Return *url* as an absolute URL.

        If *url* is relative, it is made absolute relative to the base URL of
        *self*."""
        return RequestUrl(urljoin(self._base_url, str(url)))
