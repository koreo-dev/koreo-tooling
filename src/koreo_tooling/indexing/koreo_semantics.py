from __future__ import annotations


from .semantics import Modifier, SemanticStructure


VALUE = "."
ALL = "*"


def config_step_path_indexer(value) -> str:
    try:
        label = "config"
        for key, name in value:
            if key.value == "label":
                label = name.value
                break

        return f"Step:{label}"
    except Exception as err:
        raise Exception(f"Failed to process '{value}', with {err}")


def step_path_indexer(value) -> str:
    try:
        return (
            f"Step:{''.join(name.value for key, name in value if key.value == 'label')}"
        )
    except Exception as err:
        raise Exception(f"Failed to process '{value}', with {err}")


_api_version: SemanticStructure = SemanticStructure(
    sub_structure=SemanticStructure(
        index_key_fn=lambda value: f"api_version",
        type="namespace",
    )
)

_kind: SemanticStructure = SemanticStructure(
    sub_structure=SemanticStructure(
        index_key_fn=lambda value: f"kind",
        type="type",
    ),
)

_namespace: SemanticStructure = SemanticStructure(
    sub_structure=SemanticStructure(
        type="namespace",
    ),
)

_function_ref: SemanticStructure = SemanticStructure(
    type="property",
    sub_structure=SemanticStructure(
        sub_structure={
            "name": SemanticStructure(
                type="property",
                sub_structure=SemanticStructure(
                    index_key_fn=lambda value: f"Function:{value}:ref",
                    type="function",
                ),
            ),
        },
    ),
)

_workflow_ref: SemanticStructure = SemanticStructure(
    type="property",
    sub_structure={
        "name": SemanticStructure(
            type="property",
            sub_structure=SemanticStructure(
                index_key_fn=lambda value: f"Workflow:{value}:ref",
                type="class",
            ),
        ),
    },
)

_managed_resource: SemanticStructure = SemanticStructure(
    type="property",
    sub_structure={
        "apiVersion": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="namespace"),
        ),
        "kind": SemanticStructure(
            type="parameter", sub_structure=SemanticStructure(type="type")
        ),
        "plural": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(
                type="number",
            ),
        ),
        "namespaced": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="number"),
        ),
    },
)

_behavior: SemanticStructure = SemanticStructure(
    strict_sub_structure_keys=True,
    sub_structure={
        "load": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="enumMember"),
        ),
        "create": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(
                type="number",
            ),
        ),
        "update": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="enumMember"),
        ),
        "delete": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="enumMember"),
        ),
    },
)

_function_inputs: SemanticStructure = SemanticStructure(
    type="property",
    local_key_fn=lambda value: "inputs",
    sub_structure=SemanticStructure(
        local_key_fn=lambda value: "InputValues",
        sub_structure={
            ALL: SemanticStructure(
                local_key_fn=lambda value: f"input:{value}", type="variable"
            )
        },
    ),
)

_validators = SemanticStructure(
    type="property",
    strict_sub_structure_keys=True,
    sub_structure={
        "assert": SemanticStructure(
            type="property",
            sub_structure=SemanticStructure(type="string"),
        ),
        "ok": SemanticStructure(
            type="property", strict_sub_structure_keys=True, sub_structure={}
        ),
        "skip": SemanticStructure(
            type="property",
            strict_sub_structure_keys=True,
            sub_structure={
                "message": SemanticStructure(
                    type="property",
                    sub_structure=SemanticStructure(type="string"),
                ),
            },
        ),
        "depSkip": SemanticStructure(
            type="property",
            strict_sub_structure_keys=True,
            sub_structure={
                "message": SemanticStructure(
                    type="property",
                    sub_structure=SemanticStructure(type="string"),
                ),
            },
        ),
        "retry": SemanticStructure(
            type="property",
            strict_sub_structure_keys=True,
            sub_structure={
                "message": SemanticStructure(
                    type="property",
                    sub_structure=SemanticStructure(type="string"),
                ),
                "delay": SemanticStructure(
                    type="property",
                    sub_structure=SemanticStructure(type="number"),
                ),
            },
        ),
        "permFail": SemanticStructure(
            type="property",
            strict_sub_structure_keys=True,
            sub_structure={
                "message": SemanticStructure(
                    type="property",
                    sub_structure=SemanticStructure(type="string"),
                ),
            },
        ),
    },
)

SEMANTIC_TYPE_STRUCTURE: dict[str, SemanticStructure] = {
    "Function": SemanticStructure(
        sub_structure={
            "apiVersion": _api_version,
            "kind": _kind,
            "metadata": SemanticStructure(
                sub_structure={
                    "name": SemanticStructure(
                        sub_structure=SemanticStructure(
                            index_key_fn=lambda value: f"Function:{value}:def",
                            type="function",
                            modifier=[Modifier.definition],
                        ),
                    ),
                    "namespace": _namespace,
                },
            ),
            "spec": SemanticStructure(
                strict_sub_structure_keys=True,
                sub_structure={
                    "staticResource": SemanticStructure(
                        strict_sub_structure_keys=True,
                        type="property",
                        sub_structure={
                            "managedResource": _managed_resource,
                            "behavior": _behavior,
                            "context": SemanticStructure(
                                type="property",
                                sub_structure={
                                    ALL: SemanticStructure(
                                        type="variable",
                                    )
                                },
                            ),
                        },
                    ),
                    "dynamicResource": SemanticStructure(
                        type="property",
                        strict_sub_structure_keys=True,
                        sub_structure={
                            "key": SemanticStructure(
                                type="property",
                                sub_structure=SemanticStructure(
                                    type="function",
                                    index_key_fn=lambda value: (
                                        None
                                        if value.startswith("=")
                                        else f"ResourceTemplate:{value}:ref"
                                    ),
                                ),
                            ),
                        },
                    ),
                    "inputValidators": _validators,
                    "materializers": SemanticStructure(
                        strict_sub_structure_keys=True,
                        sub_structure={
                            "base": SemanticStructure(
                                type="property",
                            ),
                            "onCreate": SemanticStructure(
                                type="property",
                            ),
                        },
                    ),
                    "outcome": SemanticStructure(
                        strict_sub_structure_keys=True,
                        sub_structure={
                            "validators": _validators,
                            "okValue": SemanticStructure(
                                sub_structure=SemanticStructure(type="string")
                            ),
                        },
                    ),
                },
            ),
        },
    ),
    "Workflow": SemanticStructure(
        sub_structure={
            "apiVersion": _api_version,
            "kind": _kind,
            "metadata": SemanticStructure(
                sub_structure=SemanticStructure(
                    sub_structure={
                        "name": SemanticStructure(
                            sub_structure=SemanticStructure(
                                index_key_fn=lambda value: f"Workflow:{value}:def",
                                type="class",
                                modifier=[Modifier.definition],
                            ),
                        ),
                        "namespace": _namespace,
                    },
                ),
            ),
            "spec": SemanticStructure(
                strict_sub_structure_keys=True,
                sub_structure={
                    "crdRef": SemanticStructure(
                        type="typeParameter",
                        strict_sub_structure_keys=True,
                        sub_structure={
                            "apiGroup": SemanticStructure(
                                type="parameter",
                                sub_structure=SemanticStructure(type="namespace"),
                            ),
                            "version": SemanticStructure(
                                type="parameter",
                                sub_structure=SemanticStructure(type="string"),
                            ),
                            "kind": SemanticStructure(
                                type="parameter",
                                sub_structure=SemanticStructure(type="class"),
                            ),
                        },
                    ),
                    "configStep": SemanticStructure(
                        local_key_fn=lambda value: f"config_step_block",
                        sub_structure=SemanticStructure(
                            local_key_fn=config_step_path_indexer,
                            strict_sub_structure_keys=True,
                            sub_structure={
                                "label": SemanticStructure(
                                    type="property",
                                    sub_structure=SemanticStructure(
                                        local_key_fn=lambda value: f"label:{value}",
                                        type="event",
                                        modifier=[Modifier.definition],
                                    ),
                                ),
                                "functionRef": _function_ref,
                                "workflowRef": _workflow_ref,
                                "inputs": _function_inputs,
                            },
                        ),
                    ),
                    "steps": SemanticStructure(
                        sub_structure=SemanticStructure(
                            sub_structure=SemanticStructure(
                                local_key_fn=step_path_indexer,
                                strict_sub_structure_keys=True,
                                sub_structure={
                                    "label": SemanticStructure(
                                        type="property",
                                        sub_structure=SemanticStructure(
                                            local_key_fn=lambda value: f"label:{value}",
                                            type="event",
                                            modifier=[Modifier.definition],
                                        ),
                                    ),
                                    "functionRef": _function_ref,
                                    "workflowRef": _workflow_ref,
                                    "inputs": _function_inputs,
                                    "mappedInput": SemanticStructure(
                                        type="property",
                                        local_key_fn=lambda value: "mapped_input",
                                        sub_structure={
                                            "source": SemanticStructure(
                                                type="argument",
                                            ),
                                            "inputKey": SemanticStructure(
                                                type="argument",
                                                sub_structure=SemanticStructure(
                                                    type="parameter",
                                                    local_key_fn=lambda value: f"input:{value}",
                                                ),
                                            ),
                                        },
                                    ),
                                    "condition": SemanticStructure(
                                        type="property",
                                        strict_sub_structure_keys=True,
                                        sub_structure={
                                            "type": SemanticStructure(
                                                type="property",
                                                sub_structure=SemanticStructure(
                                                    type="type",
                                                ),
                                            ),
                                            "name": SemanticStructure(
                                                type="property",
                                            ),
                                        },
                                    ),
                                },
                            ),
                        ),
                    ),
                },
            ),
        },
    ),
    "FunctionTest": SemanticStructure(
        sub_structure={
            "apiVersion": _api_version,
            "kind": _kind,
            "metadata": SemanticStructure(
                sub_structure=SemanticStructure(
                    sub_structure={
                        "name": SemanticStructure(
                            sub_structure=SemanticStructure(
                                index_key_fn=lambda value: f"FunctionTest:{value}:def",
                                type="function",
                                modifier=[Modifier.definition],
                            ),
                        ),
                        "namespace": _namespace,
                    },
                ),
            ),
            "spec": SemanticStructure(
                local_key_fn=lambda value: "spec",
                strict_sub_structure_keys=True,
                sub_structure={
                    "functionRef": _function_ref,
                    "currentResource": SemanticStructure(
                        type="property",
                        local_key_fn=lambda value: "current_resource",
                        sub_structure=SemanticStructure(
                            local_key_fn=lambda value: "current_value",
                        ),
                    ),
                    "inputs": _function_inputs,
                    "expectedResource": SemanticStructure(
                        type="property",
                        local_key_fn=lambda value: "expected_resource",
                        sub_structure=SemanticStructure(
                            local_key_fn=lambda value: "expected_value",
                        ),
                    ),
                    "expectedOutcome": _validators,
                    "expectedOkValue": SemanticStructure(
                        type="property",
                        local_key_fn=lambda value: "expected_ok_value",
                        sub_structure=SemanticStructure(
                            local_key_fn=lambda value: "expected_value",
                        ),
                    ),
                },
            ),
        },
    ),
    "ResourceTemplate": SemanticStructure(
        sub_structure={
            "apiVersion": _api_version,
            "kind": _kind,
            "metadata": SemanticStructure(
                sub_structure=SemanticStructure(
                    sub_structure={
                        "name": SemanticStructure(
                            sub_structure=SemanticStructure(
                                index_key_fn=lambda value: f"ResourceTemplate:{value}:def",
                                type="function",
                                modifier=[Modifier.definition],
                            ),
                        ),
                        "namespace": _namespace,
                    },
                ),
            ),
            "spec": SemanticStructure(
                strict_sub_structure_keys=True,
                sub_structure={
                    "behavior": _behavior,
                    "managedResource": _managed_resource,
                    "template": SemanticStructure(type="property"),
                },
            ),
        },
    ),
    ALL: SemanticStructure(
        sub_structure={
            "apiVersion": _api_version,
            "kind": _kind,
            "metadata": SemanticStructure(
                sub_structure=SemanticStructure(
                    sub_structure={
                        "name": SemanticStructure(
                            sub_structure=SemanticStructure(
                                modifier=[Modifier.definition],
                            ),
                        ),
                        "namespace": _namespace,
                    },
                ),
            ),
        },
    ),
}
