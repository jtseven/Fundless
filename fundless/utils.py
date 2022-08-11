from pathlib import Path
import yaml
import math
import ast
from dash import dcc
from dash import html
import dash_bootstrap_components as dbc
from xml.etree import ElementTree
import logging

logger = logging.getLogger(__name__)


def pretty_print_date(datetime):
    day = datetime.day
    if day in (1, 21, 31):
        suffix = "st"
    elif day in (2, 22):
        suffix = "nd"
    elif day in (3, 23):
        suffix = "rd"
    else:
        suffix = "th"
    return datetime.strftime(f"%e{suffix} %B %Y")


def print_crypto_amount(amount: float):
    if amount == 0:
        return "0"
    order_of_magnitude = math.floor(math.log(amount, 10))
    if order_of_magnitude < 0:
        precision = -1 * order_of_magnitude + 2
    elif order_of_magnitude < 4:
        if order_of_magnitude < 2:
            precision = 3
        else:
            precision = 2
    else:
        precision = 0
    return f"{amount:,.{precision}f}"


def parse_secrets(file_path):
    file = Path(file_path)
    with open(file) as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            logger.error("Error while parsing secrets file:")
            logger.error(exc)
            raise exc
    return data


def convert_html_to_dash(html_code):
    dash_modules = [dcc, html, dbc]
    """Convert standard html (as string) to Dash components.

    Looks into the list of dash_modules to find the right component (default to [html, dcc, dbc])."""

    def find_component(name):
        for module in dash_modules:
            try:
                return getattr(module, name)
            except AttributeError:
                pass
        raise AttributeError(f"Could not find a dash widget for '{name}'")

    def parse_css(css):
        """Convert a style in ccs format to dictionary accepted by Dash"""
        return {k: v for style in css.strip(";").split(";") for k, v in [style.split(":")]}

    def parse_value(v):
        try:
            return ast.literal_eval(v)
        except (SyntaxError, ValueError):
            return v

    parsers = {"style": parse_css, "id": lambda x: x}

    def _convert(elem):
        comp = find_component(elem.tag.capitalize())
        children = [_convert(child) for child in elem]
        if not children:
            children = elem.text
        attribs = elem.attrib.copy()
        if "class" in attribs:
            attribs["className"] = attribs.pop("class")
        attribs = {k: parsers.get(k, parse_value)(v) for k, v in attribs.items()}

        return comp(children=children, **attribs)

    et = ElementTree.fromstring(html_code)

    return _convert(et)
