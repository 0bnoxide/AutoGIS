# -*- coding: utf-8 -*-
"""toolbox.pyt — reference ArcGIS Pro Python toolbox for the AutoGIS suite.

A dumb marshaller over the installed ``autogis`` package: every tool's
``execute()`` does nothing but pull params off the GUI, hand them to
``autogis.adapters.toolbox_core`` (pure, arcpy-free), and render QA via
``_msg``. No ``sys.path`` hack — install the package (``pip install -e .``)
into the cloned ``arcgispro-py3`` env so it imports normally. See
``docs/pro-install.md``.

This file is intentionally never imported by the test suite: its top-level
``import arcpy`` only resolves inside ArcGIS Pro. The testable wiring lives in
``toolbox_core``.
"""

import arcpy

from autogis.adapters import toolbox_core
from autogis.core.common.qa import QACollector


def _msg(messages, qa: QACollector):
    for rec in qa.records:
        line = f"[{rec.severity}] {rec.category}: {rec.message}"
        if rec.severity in ("ERROR", "CRITICAL"):
            messages.addErrorMessage(line)
        elif rec.severity == "WARNING":
            messages.addWarningMessage(line)
        else:
            messages.addMessage(line)


def _param(name, display, datatype, required=True, direction="Input",
           default=None, domain=None, multi=False):
    p = arcpy.Parameter(
        displayName=display, name=name, datatype=datatype,
        parameterType="Required" if required else "Optional",
        direction=direction, multiValue=multi,
    )
    if default is not None:
        p.value = default
    if domain:
        p.filter.type = "ValueList"
        p.filter.list = list(domain)
    return p


class Toolbox(object):
    def __init__(self):
        self.label = "AutoGIS Suite"
        self.alias = "autogis"
        self.tools = [HarvestAttachments]


class HarvestAttachments(object):
    def __init__(self):
        self.label = "Harvest Attachments"
        self.description = ("Download attachments from a hosted feature layer "
                            "into grouped/templated folders. Pure marshalling "
                            "over autogis.core.harvest.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("directory", "Output directory", "DEFolder"),
            _param("group_template", "Group folder template", "GPString"),
            _param("filename_template", "Filename template", "GPString"),
            _param("url", "Feature layer URL", "GPString", required=False),
            _param("item_id", "AGOL item id", "GPString", required=False),
            _param("where", "WHERE clause", "GPString",
                   required=False, default="1=1"),
            _param("incremental", "Incremental", "GPBoolean",
                   required=False, default=False),
        ]

    def execute(self, parameters, messages):
        from autogis.runtime.sessions import pro_active_portal
        p = {q.name: q for q in parameters}
        qa = QACollector()
        config = toolbox_core.build_harvest_config(
            directory=p["directory"].valueAsText,
            group_template=p["group_template"].valueAsText,
            filename_template=p["filename_template"].valueAsText,
            url=p["url"].valueAsText or None,
            item_id=p["item_id"].valueAsText or None,
            where=p["where"].valueAsText or "1=1",
            incremental=bool(p["incremental"].value),
        )
        results = toolbox_core.run_harvest(config, pro_active_portal())
        messages.addMessage(f"{len(results)} attachment(s) processed.")
        _msg(messages, qa)
