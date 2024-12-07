import re

from koreo.function.prepare import prepare_function
from koreo.function.structure import Function
from koreo.function_test.prepare import prepare_function_test
from koreo.function_test.structure import FunctionTest
from koreo.resource_template.prepare import prepare_resource_template
from koreo.resource_template.structure import ResourceTemplate
from koreo.workflow.prepare import prepare_workflow
from koreo.workflow.structure import Workflow


API_VERSION = "koreo.realkinetic.com/v1alpha8"

PREPARE_MAP = {
    "Function": (Function, prepare_function),
    "ResourceTemplate": (ResourceTemplate, prepare_resource_template),
    "Workflow": (Workflow, prepare_workflow),
    "FunctionTest": (FunctionTest, prepare_function_test),
}

CRD_API_VERSION = "apiextensions.k8s.io/v1"
CRD_KIND = "CustomResourceDefinition"


RESOURCE_DEF = re.compile("(?P<kind>[A-Z][a-zA-Z0-9.]*):(?P<name>.*):def")

TOP_LEVEL_RESOURCE = re.compile("(?P<kind>[A-Z][a-zA-Z0-9.]*):(?P<name>.*)?:[dr]ef")

WORKFLOW_NAME = re.compile("Workflow:(?P<name>[^:]*)?:def")
FUNCTION_NAME = re.compile("Function:(?P<name>.*)?:def")
FUNCTION_TEST_NAME = re.compile("FunctionTest:(?P<name>.*)?:def")

WORKFLOW_ANCHOR = re.compile("Workflow:(?P<name>[^:]*)")
FUNCTION_ANCHOR = re.compile("Function:(?P<name>.*)")
FUNCTION_TEST_ANCHOR = re.compile("FunctionTest:(?P<name>.*)")

INPUT_NAME_PATTERN = re.compile("inputs.(?P<name>[^.]+).?")
PARENT_NAME_PATTERN = re.compile("parent.(?P<name>[^.]+).?")
