import re

from koreo.function_test.prepare import prepare_function_test
from koreo.function_test.structure import FunctionTest
from koreo.resource_function.prepare import prepare_resource_function
from koreo.resource_function.structure import ResourceFunction
from koreo.resource_template.prepare import prepare_resource_template
from koreo.resource_template.structure import ResourceTemplate
from koreo.value_function.prepare import prepare_value_function
from koreo.value_function.structure import ValueFunction
from koreo.workflow.prepare import prepare_workflow
from koreo.workflow.structure import Workflow


API_VERSION = "koreo.dev/v1beta1"

PREPARE_MAP = {
    "FunctionTest": (FunctionTest, prepare_function_test),
    "ResourceFunction": (ResourceFunction, prepare_resource_function),
    "ResourceTemplate": (ResourceTemplate, prepare_resource_template),
    "ValueFunction": (ValueFunction, prepare_value_function),
    "Workflow": (Workflow, prepare_workflow),
}

CRD_API_VERSION = "apiextensions.k8s.io/v1"
CRD_KIND = "CustomResourceDefinition"


RESOURCE_DEF = re.compile("(?P<kind>[A-Z][a-zA-Z0-9.]*):(?P<name>.*):def")

TOP_LEVEL_RESOURCE = re.compile("(?P<kind>[A-Z][a-zA-Z0-9.]*):(?P<name>.*)?:[dr]ef")

FUNCTION_TEST_NAME = re.compile("FunctionTest:(?P<name>.*)?:def")
RESOURCE_FUNCTION_NAME = re.compile("ResourceFunction:(?P<name>.*)?:def")
VALUE_FUNCTION_NAME = re.compile("ValueFunction:(?P<name>.*)?:def")
WORKFLOW_NAME = re.compile("Workflow:(?P<name>[^:]*)?:def")

FUNCTION_TEST_ANCHOR = re.compile("FunctionTest:(?P<name>.*)")
RESOURCE_FUNCTION_ANCHOR = re.compile("ResourceFunction:(?P<name>.*)")
VALUE_FUNCTION_ANCHOR = re.compile("ValueFunction:(?P<name>.*)")
WORKFLOW_ANCHOR = re.compile("Workflow:(?P<name>[^:]*)")

INPUT_NAME_PATTERN = re.compile("inputs.(?P<name>[^.]+).?")
PARENT_ROOT_PATTERN = re.compile("(?P<root>[^.]+).?")
