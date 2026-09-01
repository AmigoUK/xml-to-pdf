"""Which XPaths a generated config ends up with."""

from mapping import (
    DEFAULT_HEADER_XPATH, DEFAULT_ITEM_XPATH, MappingConfig, resolve_xpaths,
)
from xml_parser import DiscoveredSchema


def _schema(header="", item=""):
    return DiscoveredSchema(header_xpath=header, item_xpath=item,
                            header_tags=[], item_tags=[], item_count=0)


def test_discovered_xpaths_win():
    header, item = resolve_xpaths(_schema(".//Kopfdaten", ".//Position"), None)
    assert (header, item) == (".//Kopfdaten", ".//Position")


def test_loaded_config_is_used_when_nothing_was_discovered():
    loaded = MappingConfig(header_xpath=".//Naglowek", item_xpath=".//Pozycja")
    header, item = resolve_xpaths(None, loaded)
    assert (header, item) == (".//Naglowek", ".//Pozycja")


def test_loaded_config_is_used_when_discovery_came_back_empty():
    loaded = MappingConfig(header_xpath=".//Cabecera", item_xpath=".//LineaFactura")
    header, item = resolve_xpaths(_schema("", ""), loaded)
    assert (header, item) == (".//Cabecera", ".//LineaFactura")


def test_falls_back_to_the_shared_defaults():
    header, item = resolve_xpaths(None, None)
    assert (header, item) == (DEFAULT_HEADER_XPATH, DEFAULT_ITEM_XPATH)


def test_a_partial_discovery_is_completed_from_the_loaded_config():
    loaded = MappingConfig(header_xpath=".//Cabecera", item_xpath=".//LineaFactura")
    header, item = resolve_xpaths(_schema(".//EnTete", ""), loaded)
    assert header == ".//EnTete"
    assert item == ".//LineaFactura"
