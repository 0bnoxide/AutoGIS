"""Packaged static assets for the HTML report render layer (report.css).

A real package (not a bare dir) so importlib.resources.files() can resolve it
and setuptools package-data ships the .css in a wheel/non-editable install.
"""
